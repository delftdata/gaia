import argparse
import subprocess as sp
from datetime import datetime
import re
import os
from os.path import join
import time
import logging

VALID_ACTIONS = ['benchmark', 'collect_client', 'collect_server']
VALID_WORKLOADS = ['ycsb', 'tpcc', 'pps', 'smallbank', 'movr', 'movie', 'dsh']

LOG_FORMAT = "%(asctime)s %(name)10s %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
LOG = logging.getLogger("admin")

def run_remote(ip, cmd, user):
    """Executes a command on a remote host via SSH."""
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no {user}@{ip} \"{cmd}\""
    # Using check=False because the teardown might fail if container doesn't exist
    return sp.run(ssh_cmd, shell=True, capture_output=True, text=True)

def benchmark_ycsb(server_ips, image, user, clients, duration, params, seed, txns, workload, prime_region_ips, client_ips):
    mp = 0.5
    if 'mp=' in params:
        mp = int(params.split('mp=')[1].split(',')[0])/100.0
    mh = 0.5
    if 'mh=' in params:
        mh = int(params.split('mh=')[1].split(',')[0])/100.0
    nparts = len(server_ips) / len(prime_region_ips)
    nregs = len(prime_region_ips)
    skew = 0.0
    if 'skew=' in params:
        skew = float(params.split('skew=')[1].split(',')[0])

    # 2. Clean up any old benchmark containers
    LOG.info("--- Cleaning up old benchmark containers on client machines ---")
    for client_ip in client_ips:
        result = run_remote(client_ip, "docker rm -f crdb-client || true", user)
        if result.returncode != 0:
            LOG.warning("  - Warning: Failed to clean up old containers on %s: %s", client_ip, result.stderr)
        else:
            LOG.info("  - Cleaned up old containers on %s", client_ip)

    # 3. Launch on each machine
    for i, (client_ip, prime_region_ip) in enumerate(zip(client_ips, prime_region_ips)):
        LOG.info("Deploying to %s (Region %s)...", client_ip, i)

        # Construct the C++ execution command inside Docker
        # Mapping: ./benchmark_crdb <IP> <threads> <read_%> <skew> <multi_part_%> <multi_home_%> <num_parts> <num_regs> <client_reg> <duration>
        # Note: IP inside Docker should hit the host IP (auto-detected by C++ script)
        cpp_cmd = (
            #                  <ip>              <threads> <read_%> <skew> <multi_part_%> <multi_home_%> <num_parts>     <num_regs>     <duration>   <client_region>
            f"./benchmark_crdb {prime_region_ip} {clients} 0        {skew} {mp}           {mh}           {int(nparts)}   {int(nregs)}   {duration}   {i} "
        )
        LOG.info("  - C++ Command: %s", cpp_cmd)
        docker_cmd = (
            f"docker run -d --name crdb-client --net=host {image} {cpp_cmd}"
        )
        LOG.info("  - Running command: %s", docker_cmd)
        result = run_remote(client_ip, docker_cmd, user)
        
        if result.returncode == 0:
            LOG.info("Successfully started benchmark on %s", client_ip)
        else:
            LOG.warning("Failed to start on %s: %s", client_ip, result.stderr)

    time.sleep(duration+5) # Give time for containers actually run the benchmarks
    benchmark_complete = False
    while not benchmark_complete:
        benchmark_complete = True
        for client_ip in client_ips:
            result = run_remote(client_ip, "docker logs crdb-client", user)
            if result.returncode != 0:
                LOG.warning("  - Warning: Failed to get logs from %s: %s", client_ip, result.stderr)
                continue
            logs = result.stdout + result.stderr
            if "--- RESULTS ---" not in logs:
                benchmark_complete = False
                LOG.info("  - Benchmark still running on %s...", client_ip)
                #LOG.info("    Logs: %s", logs.splitlines()[-5:]) # Print last 5 lines of logs for debugging
        if not benchmark_complete:
            time.sleep(5) # Wait before checking again

    LOG.info("--- All clients spawned. Use 'docker logs -f crdb-client' on nodes to monitor. ---")
    tag = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    LOG.info("Tag: %s", tag)

def benchmark_tpcc(server_ips, image, user, clients, duration, params, seed, txns, workload, prime_region_ips, client_ips, scenario='scalability'):
    # 1. Parse TPC-C specific parameters
    # Expected format: "warehouses=1200,active=50"
    total_warehouses = 1200
    if 'warehouses=' in params:
        total_warehouses = int(params.split('warehouses=')[1].split(',')[0])

    active_warehouses = clients
    if 'active=' in params:
        active_warehouses = int(params.split('active=')[1].split(',')[0])
    workers=10*clients
    
    wait = 'true'
    if scenario == 'skew':
        wait = 'false' # For skew experiments we want to run for a fixed number of transactions instead of a fixed duration, so we disable waiting in the C++ tool and will monitor logs ourselves to determine when the benchmark is done.

    nregs = len(prime_region_ips)

    # 2. Clean up any old benchmark containers
    LOG.info("--- Cleaning up old benchmark containers on client machines ---")
    for client_ip in client_ips:
        result = run_remote(client_ip, "docker rm -f crdb-client || true", user)
        if result.returncode != 0:
            LOG.warning("  - Warning: Failed to clean up old containers on %s: %s", client_ip, result.stderr)
        else:
            LOG.info("  - Cleaned up old containers on %s", client_ip)

    # 3. Launch on each machine
    for i, (client_ip, prime_region_ip) in enumerate(zip(client_ips, prime_region_ips)):
        LOG.info("Deploying TPC-C to %s (Region %s)...", client_ip, i)

        # Build the cockroach workload command
        # We use --partition-strategy=leases to prevent the tool from trying to re-partition 
        # based on 'racks' which caused your earlier error.
        tpcc_cmd = (
            f"workload run tpcc "
            f"--duration={duration}s "
            f"--warehouses={total_warehouses} "
            f"--active-warehouses={active_warehouses} "
            f"--concurrency={clients} "
            f"--workers={workers} "
            f"--wait={wait} "
            f"--partitions={nregs} "
            f"--partition-affinity={i} "
            f"--partition-strategy=leases "
            #f"--local-warehouses " # Usefull for the 0% geo-distribution in the Baseline scenario
            f"--db=geo_bench "
            f"--seed={seed + i} "
            f"'postgresql://root@{prime_region_ip}:26257?sslmode=disable'"
        )

        # Note: We don't use --net=host here if we want isolation, 
        # but your YCSB used it, so I'll keep it for consistency.
        docker_cmd = f"docker run -d --name crdb-client --net=host {image} {tpcc_cmd}"
        
        LOG.info("  - Running command: %s", docker_cmd)
        result = run_remote(client_ip, docker_cmd, user)
        
        if result.returncode == 0:
            LOG.info("Successfully started TPC-C on %s", client_ip)
        else:
            LOG.warning("Failed to start on %s: %s", client_ip, result.stderr)

    # 4. Monitor logs for completion
    time.sleep(duration + 10)
    benchmark_complete = False
    while not benchmark_complete:
        benchmark_complete = True
        for client_ip in client_ips:
            # TPC-C prints a summary at the end. We look for the "Audit check" or "tpmC" results.
            result = run_remote(client_ip, "docker logs crdb-client", user)
            logs = result.stdout + result.stderr
            if "_elapsed_______tpmC____efc" not in logs and "Error: ":
                benchmark_complete = False
                LOG.info("  - TPC-C still running on %s...", client_ip)
        if not benchmark_complete:
            time.sleep(10)
    
    LOG.info("✅ TPC-C Benchmark Run Complete.")
    tag = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    LOG.info("Tag: %s", tag)

def main():
    parser = argparse.ArgumentParser(description="Spawn remote C++ benchmark clients.")
    parser.add_argument('-a',  '--action', choices=VALID_ACTIONS, required=True, help="Action to perform")
    parser.add_argument('-co', '--config', default='examples/ycsb/tu_cluster_ycsb_crdb.conf', help="Path to the configuration file")
    parser.add_argument('-i',  '--image', default="omraz/seq_eval:crdb_benchmark", help="Docker image containing test_crdb")
    parser.add_argument('-u',  '--user', default="omraz", help="SSH user")
    parser.add_argument('-c',  '--clients', type=int, default=4, help="Threads per client machine")
    parser.add_argument('-d',  '--duration', type=int, default=60, help="Benchmark duration in seconds")
    parser.add_argument('-p',  '--params', default="mh=50,mp=50", help="Workload params: <param1>=<val1>,<param2>=<val2>,...")
    parser.add_argument('-s',  '--seed', type=int, default=1, help="Base seed for randomization")
    parser.add_argument('-t',  '--txns', type=int, default=2_000_000, help="Number of transactions to run (if applicable)")
    parser.add_argument('-wl', '--workload', choices=VALID_WORKLOADS, default='ycsb', help="Workload type for benchmarking")
    parser.add_argument('-od', '--out-dir', default='data', help="Base output directory for collected results")
    parser.add_argument('-ta', '--tag', default=None, help="Custom tag for this experiment run (overrides timestamp)")
    parser.add_argument('-sc', '--scenario', default='scalability', help="Experiment scenario (used for TPC-C benchmarks to determine params)")
    
    ''' Default arguments for quick testing:
action='benchmark'
conf='examples/ycsb/tu_cluster_ycsb_crdb.conf'
image='omraz/seq_eval:crdb_benchmark'
user='omraz'
clients=2
duration=60
params='mh=50,mp=50'
seed=1
    '''

    args = parser.parse_args()
    action = args.action
    conf = args.config
    image = args.image
    user = args.user
    clients = args.clients
    duration = args.duration
    params = args.params
    seed = args.seed
    txns = args.txns
    workload = args.workload
    out_dir = args.out_dir
    tag = args.tag
    scenario = args.scenario

    # 1. Parse configuration to find where to launch clients
    with open(conf, 'r') as f:
        conf_contents = f.readlines()
    #conf_contents = conf_contents.split('\n')

    server_ips = []
    prime_region_ips = []
    client_ips = []
    for l in conf_contents:
        if '    addresses: "' in l:
            ip = l.split('addresses: "')[1].split('"')[0]
            server_ips.append(ip)
            if len(prime_region_ips) == len(client_ips):
                prime_region_ips.append(ip)
        elif '    client_addresses: "' in l:
            ip = l.split('client_addresses: "')[1].split('"')[0]
            client_ips.append(ip)
    
    if server_ips == [] or client_ips == []:
        LOG.info("No client addresses found in config.")
        return
    LOG.info("--- Launching Benchmark on %s machines ---", len(client_ips))

    LOG.info("IPs involved:")
    LOG.info("  - Servers: %s", server_ips)
    LOG.info("  - Prime Region Servers: %s", prime_region_ips)
    LOG.info("  - Clients: %s", client_ips)

    if action == 'benchmark':
        if workload == 'ycsb':
            benchmark_ycsb(server_ips, image, user, clients, duration, params, seed, txns, workload, prime_region_ips, client_ips)
        elif workload == 'tpcc':
            benchmark_tpcc(server_ips, image, user, clients, duration, params, seed, txns, workload, prime_region_ips, client_ips, scenario)
        else:
            LOG.warning("Workload %s not supported for benchmarking yet.", workload)

    elif action == 'collect_client':
        # 1. Create the timestamped base directory
        # Format: exp_20240204_153022
        '''timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")'''
        base_dir = join("data", tag)

        LOG.info("--- Collecting Results into %s ---", base_dir)
        
        for i, client_ip in enumerate(client_ips):
            # 2. Define and create the specific subdirectory for this client
            client_dir = os.path.join(base_dir, "client", f"0-{i}")
            os.makedirs(client_dir, exist_ok=True)

            LOG.info("Collecting logs from client %s...", client_ip)
            
            # 3. Securely copy the files from the remote host
            # We assume the files were written to /app inside the container 
            # and thus exist at the remote path /app/ on the host (if mapped) 
            # or we pull directly from the container's filesystem via ssh + docker cp
            
            # Strategy: Use docker cp on the remote host to move files out of the container to a temp area, 
            # then scp them to the local machine.
            # Extract files from container to remote host /tmp first to avoid path permissions issues
            remote_tmp = f"/tmp/client_{i}_results"

            if workload == 'ycsb':
                run_remote(client_ip, f"mkdir -p {remote_tmp}", user)
                run_remote(client_ip, f"docker cp crdb-client:/app/summary.csv {remote_tmp}/summary.csv", user)
                run_remote(client_ip, f"docker cp crdb-client:/app/transactions.csv {remote_tmp}/transactions.csv", user)
                run_remote(client_ip, f"docker cp crdb-client:/app/metadata.csv {remote_tmp}/metadata.csv", user)
                run_remote(client_ip, f"docker cp crdb-client:/app/txn_events.csv {remote_tmp}/txn_events.csv", user)

                # SCP from remote host /tmp to local experiment directory
                sp.run(f"scp {user}@{client_ip}:{remote_tmp}/summary.csv {client_dir}/summary.csv", shell=True)
                sp.run(f"scp {user}@{client_ip}:{remote_tmp}/transactions.csv {client_dir}/transactions.csv", shell=True)
                sp.run(f"scp {user}@{client_ip}:{remote_tmp}/metadata.csv {client_dir}/metadata.csv", shell=True)
                sp.run(f"scp {user}@{client_ip}:{remote_tmp}/txn_events.csv {client_dir}/txn_events.csv", shell=True)
            elif workload == 'tpcc':
                # For now all the TPC-C results are in the docker container logs anyway, so we don't need to copy files here.
                pass
            else:
                LOG.warning("Workload %s not supported for client data collection yet.", workload)

        LOG.info("✅ All results stored in %s", base_dir)

if __name__ == "__main__":
    main()