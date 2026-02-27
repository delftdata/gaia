import json
import subprocess as sp
import time
import argparse
import os, sys
import psycopg2
import io
import concurrent.futures

TARGET_DB_NAME = "geo_bench"
NO_REPLICAS = 3
YCSB_ROW_COUNT = 10_000_000 # 10 million rows (100M runs out of memory)
TPCC_WAREHOUSE_COUNT = 1200 # 1200 warehouses is ~100GB of data, which is a good starting point for testing. Scale up as needed.
YCSB_TABLE_NAME = "usertable"
ROW_INSERT_BATCH = 10_000
CRDB_PORT = 26257
VALID_CONFIG_JSONS = ['crdb/tu_cluster_crdb.json', 'aws/aws_crdb.json']
VALID_ACTIONS = ['start', 'stop', 'populate', 'partition']
DEFAULT_USER = "omraz"

aws_neighbour_region_map = {
    "euw1": "euw2",
    "euw2": "euw1",
    "usw1": "usw2",
    "usw2": "usw1",
    "use1": "use2",
    "use2": "use1",
    "apne1": "apne2",
    "apne2": "apne1"
}

def run_remote(ip, cmd, user=DEFAULT_USER):
    """Executes a command on a remote host via SSH."""
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no {user}@{ip} \"{cmd}\""
    #print(f"Running remote command on {ip}: \n{ssh_cmd}")
    result = sp.run(ssh_cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error on {ip}: {result.stderr}")
    return result

def stop_node(ip, user, password=None):
    """Logic for a single node stop/clean"""
    print(f"Stopping and cleaning node at {ip}...")
    # 1. Forcefully remove the Docker container
    run_remote(ip, "docker rm -f crdb-node || true", user)
    # 2. Kill ghost processes
    kill_cmd = "pkill -9 cockroach || true"
    if password:
        run_remote(ip, f"echo {password} | sudo -S -p '' {kill_cmd}", user)
    else:
        run_remote(ip, f"sudo {kill_cmd}", user)
    # 3. Wipe the physical data directory
    data_path = f"/home/{user}/cockroach-data"
    wipe_cmd = f"rm -rf {data_path}/*"
    if password:
        run_remote(ip, f"echo {password} | sudo -S -p '' {wipe_cmd}", user)
    else:
        run_remote(ip, f"sudo {wipe_cmd}", user)
    # 4. Cleanup Docker networking
    run_remote(ip, "docker network prune -f", user)
    return f"Done: {ip}"

def stop_cluster_parallel(all_ips, user, password=None):
    print("--- Action: Stopping Cluster (Parallel) ---")
    # max_workers should be len(all_ips) so everyone starts at once
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(all_ips)) as executor:
        # Map the stop_node function to all IPs
        future_to_ip = {executor.submit(stop_node, ip, user, password): ip for ip in all_ips}
        for future in concurrent.futures.as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                data = future.result()
                print(f"Successfully cleaned {ip}")
            except Exception as exc:
                print(f"Node {ip} generated an exception: {exc}")

def setup_and_launch_node(ip, region, image, join_str, user, env, cpus=16, memory=128):
    """Merged Pull and Launch for a single node"""
    print(f"[{ip}] Starting full setup...")
    # 1. Pull the image first
    pull_result = run_remote(ip, f"docker pull {image}", user)
    if pull_result.returncode != 0:
        return f"FAILED PULL on {ip}: {pull_result.stderr}"
    # 2. Immediately launch the container
    #data_path = f"/home/{user}/cockroach-data"
    data_path = "/dev/shm/cockroach-data"
    docker_cmd = (
        f'docker run -d --name crdb-node --memory="{memory}g" --cpus="{cpus}" --net=host '
        f'-v {data_path}:/cockroach/cockroach-data {image} '
        f'start --insecure --advertise-addr={ip} '
        f'--locality=region={region} --join={join_str} --store=/cockroach/cockroach-data'
    )
    launch_result = run_remote(ip, docker_cmd, user)
    if launch_result.returncode != 0:
        return f"FAILED LAUNCH on {ip}: {launch_result.stderr}"
    return f"SUCCESS on {ip}"

def start_cluster_parallel(all_ips, cluster_config, image, user, env, cpus=16, memory=128):
    join_str = ",".join(all_ips)
    print("--- Action: Merged Parallel Startup ---")
    tasks = []
    for region, ips in cluster_config.items():
        for ip in ips:
            tasks.append((ip, region))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(all_ips)) as executor:
        # We pass the shared variables (image, join_str, user) via a lambda or partial
        future_to_node = {
            executor.submit(setup_and_launch_node, ip, reg, image, join_str, user, env, cpus, memory): ip 
            for ip, reg in tasks
        }
        for future in concurrent.futures.as_completed(future_to_node):
            print(future.result())
    time.sleep(5) # Give some time for all nodes to start before we proceed with initialization

def initialize_and_setup_cluster(primary_ip, license_path, env, user=DEFAULT_USER, regions=['usw', 'euw'], primary_region="euw1"):
    print("Initializing cluster...")
    # This may fail if the cluster was already initialized; ignore error
    init_cluster_cmd = f"docker exec crdb-node ./cockroach init --insecure --host={primary_ip}"
    result = run_remote(primary_ip, init_cluster_cmd, user=user)
    if result.returncode != 0:
        print(f"Initialization may have already been done or failed: {result.stderr}")
    else:
        print("✅ Cluster initialized successfully.")

    # 4. License & Geo-Setup
    if license_path:
        print("Applying License and Geo-settings...")
        time.sleep(10) # Wait for consensus
        with open(license_path) as f:
            license_data = json.load(f)
            org = license_data['organization']
            lic = license_data['key']

        sql = f"""
            SET CLUSTER SETTING cluster.organization = '{org}';
            SET CLUSTER SETTING enterprise.license = '{lic}';
            DROP DATABASE IF EXISTS {TARGET_DB_NAME} CASCADE;
            CREATE DATABASE {TARGET_DB_NAME};
            USE {TARGET_DB_NAME};
        """
        # This is for a native multi-region fault-tolerant setup.
        # Omit for now since we can geo-partition differently
        '''for r in regions:
            if r != primary_region:
                sql += f"""
                ALTER DATABASE {TARGET_DB_NAME} PRIMARY REGION {primary_region};
                ALTER DATABASE {TARGET_DB_NAME} ADD REGION {r};\n
                """
        if env == 'aws':
            sql += f"""
            ALTER DATABASE {TARGET_DB_NAME} SURVIVE REGION FAILURE;
            """
        else:
            sql += f"""
            """'''
        # Use a single-line or properly escaped multi-line SQL string
        # We wrap the whole thing in a heredoc to prevent the shell from breaking on newlines
        license_and_geo_cmd = f"""
docker exec -i crdb-node ./cockroach sql --insecure --host={primary_ip} <<'EOF'
{sql}
EOF
"""
        result = run_remote(primary_ip, license_and_geo_cmd, user=user)
        if result.returncode == 0:
            print("✅ License and geo-settings applied successfully.")
        #sp.run(f"echo \"{sql}\" | docker exec -i crdb-node ./cockroach sql --insecure --host={primary_ip}", shell=True)

def populate_ycsb(primary_ip, user, regions_list, row_count=YCSB_ROW_COUNT, robust_mode=True, env='st'):
    row_count = YCSB_ROW_COUNT
    print(f"--- Manually Populating YCSB: {int(row_count/1_000_000)}M rows ---")
    # Connect to the primary node
    conn = psycopg2.connect(
        host=primary_ip,
        port=CRDB_PORT,
        user='root',
        database=TARGET_DB_NAME,
        sslmode='disable'
    )
    conn.autocommit = True
    cur = conn.cursor()
    # 1. Prepare Schema
    cur.execute(f"DROP TABLE IF EXISTS {YCSB_TABLE_NAME};")
    cur.execute(f"CREATE TABLE {YCSB_TABLE_NAME} (ycsb_key BIGINT PRIMARY KEY, field0 BYTES);")

    # 2. Apply Partitioning & Zone Config BEFORE data load
    num_regions = len(regions_list)
    step = row_count // num_regions
    print(f"--- Applying {num_regions}-Region Geo-Partitioning ---")
    partition_defs = []
    for i, reg in enumerate(regions_list):
        p_name = f"p{i+1}"
        start = i * step
        end = (i + 1) * step
        if i == 0:
            partition_defs.append(f"PARTITION {p_name} VALUES FROM (MINVALUE) TO ({end})")
        elif i == num_regions - 1:
            partition_defs.append(f"PARTITION {p_name} VALUES FROM ({start}) TO (MAXVALUE)")
        else:
            partition_defs.append(f"PARTITION {p_name} VALUES FROM ({start}) TO ({end})")
    
    partition_sql = f"ALTER TABLE {YCSB_TABLE_NAME} PARTITION BY RANGE (ycsb_key) ({', '.join(partition_defs)});"
    cur.execute(partition_sql)

    print("--- Applying Zone Configurations ---")
    for i, region in enumerate(regions_list):
        p_name = f"p{i+1}"
        if env == 'st':
            other_region = regions_list[(i + 1) % num_regions]
            constraints = f"{{+region={region}: 2, +region={other_region}: 1}}"
        elif env == 'aws':
            if robust_mode:
                # Use the neighbor map to find a close-by region for the 3rd replica
                other_region = aws_neighbour_region_map.get(region, regions_list[(i + 1) % num_regions])
                constraints = f"{{+region={region}: 2, +region={other_region}: 1}}"
                #print(f"  {p_name}: Primary home {region}, Safety replica in {other_region}")
            else:
                # Max Performance: All 3 replicas local
                constraints = f"{{+region={region}: 3}}"
                print(f"  {p_name}: All 3 replicas pinned to {region}")

        zone_sql = f"""
            ALTER PARTITION {p_name} OF TABLE {YCSB_TABLE_NAME} CONFIGURE ZONE USING 
            num_replicas = {NO_REPLICAS},
            lease_preferences = '[[+region={region}]]', 
            constraints = '{constraints}';
        """
        cur.execute(zone_sql)

    # Force the empty partitions to move to their respective regions
    print("--- Moving empty partitions to their regions ---")
    cur.execute(f"ALTER TABLE {YCSB_TABLE_NAME} SCATTER;")

    '''# --- PRE-SPLIT STEP ---
    # We split the table into chunks of 1 million rows across the 100M range
    print(f"--- Pre-splitting table for {int(row_count/1_000_000)}M rows ---")
    for i in range(1, 100):
        split_point = i * 1000000
        cur.execute(f"ALTER TABLE {YCSB_TABLE_NAME} SPLIT AT VALUES ({split_point});")
    # ---------------------------'''
    # 3. Generate and Stream data using COPY (much faster than INSERT)
    # We use a memory buffer to stream the data
    print(f"--- Streaming {int(row_count/1_000_000)}M rows ---")
    cur_rows = 0
    while cur_rows < row_count:
        batch_size = min(ROW_INSERT_BATCH, row_count - cur_rows)
        buf = io.BytesIO()
        for i in range(cur_rows, cur_rows + batch_size):
            key = str(i).encode()
            val = os.urandom(100).hex().encode()
            buf.write(key + b"\t\\x" + val + b"\n")
        cur_rows += batch_size
        success = False
        retries = 0
        while not success and retries < 5:
            try:
                buf.seek(0)
                cur.copy_expert(f"COPY {YCSB_TABLE_NAME} FROM STDIN", buf)
                success = True
            except psycopg2.errors.SerializationFailure:
                retries += 1
                print(f"\nRetry {retries} for batch starting at {cur_rows}...")
                time.sleep(1) # Small backoff
        print(f"Inserted {cur_rows}/{int(row_count/1_000_000)}M rows...", end='\r')
    print(f"Finished inserting {int(row_count/1_000_000)}M rows.")

    cur.close()
    conn.close()
    print("✅ Custom population complete.")

def populate_tpcc(primary_ip, user, warehouse_count=TPCC_WAREHOUSE_COUNT):
    """
    Uses the native cockroach workload tool to populate TPC-C.
    'warehouses' is the scaling factor. 1000 warehouses is ~100GB of data.
    """
    print(f"--- Action: Populating TPC-C with {warehouse_count} warehouses ---")
    
    # 1. 'fixture' tells CRDB to generate the schema and the data
    # We point it to the local node to minimize network overhead during generation
    tpcc_load_cmd = (
        f"docker exec crdb-node ./cockroach workload init tpcc "
        f"--warehouses={warehouse_count} --db={TARGET_DB_NAME} --drop "
        f"'postgresql://root@localhost:26257?sslmode=disable'"
    )
    print(f"Running TPC-C load command on primary node {primary_ip} with command:\n{tpcc_load_cmd}")
    
    result = run_remote(primary_ip, tpcc_load_cmd, user=user)
    if result.returncode == 0:
        print("✅ TPC-C Data Loaded successfully.")
    else:
        print(f"❌ TPC-C Load failed: {result.stderr}")

def apply_tpcc_geo_partitioning(primary_ip, regions_list, warehouse_count=TPCC_WAREHOUSE_COUNT, user=DEFAULT_USER, env='st', robust_mode=True):
    """
    Partitions all TPC-C tables and indexes by Warehouse ID.
    """
    print(f"--- Action: Applying TPC-C Geo-Partitioning for {len(regions_list)} regions ---")
    num_regions = len(regions_list)
    warehouses_per_region = warehouse_count // num_regions
    
    # Table to Column Map for TPC-C (to know which column to partition on)
    tpcc_col_map = {
        "warehouse": "w_id",
        "district": "d_w_id",
        "customer": "c_w_id",
        "history": "h_w_id",
        "\\\"order\\\"": "o_w_id",
        "new_order": "no_w_id",
        "order_line": "ol_w_id",
        "stock": "s_w_id"
    }
    sql_commands = [f"USE {TARGET_DB_NAME};"]

    for table, w_col in tpcc_col_map.items():
        parts = []
        for i, reg in enumerate(regions_list):
            cur_table = table.replace('\"', '').replace('\\', '')
            p_name = f"part_{cur_table}_{reg.replace('-', '_')}"
            start = i * warehouses_per_region
            end = (i + 1) * warehouses_per_region
            
            if i == 0:
                parts.append(f"PARTITION {p_name} VALUES FROM (MINVALUE) TO ({end})")
            elif i == num_regions - 1:
                parts.append(f"PARTITION {p_name} VALUES FROM ({start}) TO (MAXVALUE)")
            else:
                parts.append(f"PARTITION {p_name} VALUES FROM ({start}) TO ({end})")

        sql_commands.append(f"ALTER TABLE {table} PARTITION BY RANGE ({w_col}) ({', '.join(parts)});")

        for i, reg in enumerate(regions_list):
            cur_table = table.replace('\"', '').replace('\\', '')
            p_name = f"part_{cur_table}_{reg.replace('-', '_')}"
            if env == 'st':
                other_region = regions_list[(i + 1) % num_regions]
                constraints = f"{{+region={reg}: 2, +region={other_region}: 1}}"
            elif env == 'aws':
                if robust_mode:
                    # Use the neighbor map to find a close-by region for the 3rd replica
                    other_region = aws_neighbour_region_map.get(reg, regions_list[(i + 1) % num_regions])
                    constraints = f"{{+region={reg}: 2, +region={other_region}: 1}}"
                    #print(f"  {p_name}: Primary home {reg}, Safety replica in {other_region}")
                else:
                    # Max Performance: All 3 replicas local
                    constraints = f"{{+region={reg}: 3}}"
                    print(f"  {p_name}: All 3 replicas pinned to {reg}")
            sql_commands.append(f"ALTER PARTITION {p_name} OF TABLE {table} CONFIGURE ZONE USING num_replicas = 3, constraints = '{constraints}', lease_preferences = '[[+region={reg}]]';")
        
        # We add the SCATTER here so it runs inside the safe SQL context
        sql_commands.append(f"ALTER TABLE {table} SCATTER;")

    full_sql = "\n".join(sql_commands)
    # Using the heredoc (EOF) method is much safer for complex SQL
    partition_cmd = f"docker exec -i crdb-node ./cockroach sql --insecure --host={primary_ip} <<'EOF'\n{full_sql}\nEOF"
    #print(f"Sending TPC-C Partitioning SQL to {primary_ip} with command:\n{partition_cmd}")
    run_remote(primary_ip, partition_cmd, user=user)

    print("✅ TPC-C Geo-Partitioning complete.")

def apply_tpcc_index_partitioning(primary_ip, regions_list, warehouse_count=TPCC_WAREHOUSE_COUNT, user=DEFAULT_USER, env='st', robust_mode=True):
    print(f"--- Action: Applying TPC-C Index Geo-Partitioning for {len(regions_list)} regions ---")
    
    num_regions = len(regions_list)
    warehouses_per_region = warehouse_count // num_regions
    sql_commands = [f"USE {TARGET_DB_NAME};"]
    
    # customer_idx on customer and order_idx on "order"
    index_targets = [
        ("customer", "customer_idx", "c_w_id"), 
        ("\\\"order\\\"", "order_idx", "o_w_id")
    ]

    for table, idx, col in index_targets:
        parts = []
        for i, reg in enumerate(regions_list):
            cur_table = table.replace('\"', '').replace('\\', '')
            p_name = f"idx_p{i+1}_{cur_table}"
            start = i * warehouses_per_region
            end = (i + 1) * warehouses_per_region
            
            # Match the boundary logic used in the table partitioning
            if i == 0:
                parts.append(f"PARTITION {p_name} VALUES FROM (MINVALUE) TO ({end})")
            elif i == num_regions - 1:
                parts.append(f"PARTITION {p_name} VALUES FROM ({start}) TO (MAXVALUE)")
            else:
                parts.append(f"PARTITION {p_name} VALUES FROM ({start}) TO ({end})")
        
        # 1. Apply Partitions to the Index
        sql_commands.append(f"ALTER INDEX {table}@{idx} PARTITION BY RANGE ({col}) ({', '.join(parts)});")
        
        # 2. Pin each partition to its respective region
        for i, reg in enumerate(regions_list):
            cur_table = table.replace('\"', '').replace('\\', '')
            p_name = f"idx_p{i+1}_{cur_table}"
            if env == 'st':
                other_region = regions_list[(i + 1) % num_regions]
                constraints = f"{{+region={reg}: 2, +region={other_region}: 1}}"
            elif env == 'aws':
                if robust_mode:
                    # Use the neighbor map to find a close-by region for the 3rd replica
                    other_region = aws_neighbour_region_map.get(reg, regions_list[(i + 1) % num_regions])
                    constraints = f"{{+region={reg}: 2, +region={other_region}: 1}}"
                    #print(f"  {p_name}: Primary home {reg}, Safety replica in {other_region}")
                else:
                    # Max Performance: All 3 replicas local
                    constraints = f"{{+region={reg}: 3}}"
                    print(f"  {p_name}: All 3 replicas pinned to {reg}")
            sql_commands.append(f"ALTER PARTITION {p_name} OF INDEX {table}@{idx} CONFIGURE ZONE USING num_replicas = 3, constraints = '{constraints}', lease_preferences = '[[+region={reg}]]';")

    # 3. Handle 'item' as a Global Table
    # This puts 3 replicas in EVERY region in regions_list
    item_constraints = ", ".join([f"+region={r}: 3" for r in regions_list])
    sql_commands.append(f"ALTER TABLE item CONFIGURE ZONE USING num_replicas = {3 * num_regions}, constraints = '{{{item_constraints}}}';")

    # Execute all SQL in one shot via EOF
    full_sql = "\n".join(sql_commands)
    partition_cmd = f"docker exec -i crdb-node ./cockroach sql --insecure --host={primary_ip} <<'EOF'\n{full_sql}\nEOF"
    print(f"Sending TPC-C Partitioning SQL to {primary_ip} with command:\n{partition_cmd}")
    run_remote(primary_ip, partition_cmd, user=user)

    print("✅ TPC-C index partitioning and global table setup complete.")

def populate_db_tables(all_ips, primary_ip, workload='ycsb', env='st', regions_list=['usw', 'euw'], robust_mode=True, user=DEFAULT_USER):
    print(f"Populating database using {workload} workload...")
    if workload == 'ycsb':
        populate_ycsb(primary_ip, user, regions_list, user, robust_mode=robust_mode, env=env)
        # We run the C++ benchmark in a separate step to give users time to inspect the cluster state after population and before the load test
        
    elif workload == 'tpcc':
        partition_indexes = True # We want to partition indexes for better performance, especially on larger scale factors

        # 1. Use the workload tool to build schema and load data
        # Note: TPC-C is heavy. Start with 100-500 warehouses for testing.
        populate_tpcc(primary_ip, user, warehouse_count=TPCC_WAREHOUSE_COUNT)
        
        # 2. Apply Partitioning
        # TPC-C partitioning is different! It's usually based on the 'w_id' (Warehouse ID)
        apply_tpcc_geo_partitioning(primary_ip, regions_list, warehouse_count=TPCC_WAREHOUSE_COUNT, user=user, env=env, robust_mode=robust_mode)

        if partition_indexes:
            # 3. Partition the secondary indexes for better performance (optional but recommended for TPC-C)
            apply_tpcc_index_partitioning(primary_ip, regions_list, warehouse_count=TPCC_WAREHOUSE_COUNT, user=user, env=env, robust_mode=robust_mode)
    else:
        print("Unsupported workload type.")
        return

    print("Database population completed.")

def wait_for_cluster_ready(primary_ip, timeout=300):
    """
    Polls the cluster until there are no under-replicated ranges 
    and no active rebalance jobs.
    """
    print("--- Action: Waiting for Cluster Stability ---")
    conn = psycopg2.connect(
        host=primary_ip,
        port=CRDB_PORT,
        user='root',
        database=TARGET_DB_NAME,
        sslmode='disable'
    )
    conn.autocommit = True
    cur = conn.cursor()

    start_time = time.time()
    while time.time() - start_time < timeout:
        # 1. Check for under-replicated or unavailable ranges
        cur.execute(f"""
            SELECT sum(case when array_length(replicas, 1) < {NO_REPLICAS} then 1 else 0 end)
            FROM crdb_internal.ranges 
            WHERE table_name = '{YCSB_TABLE_NAME}';
        """)
        under_rep = cur.fetchone()[0] or 0
        
        # 2. Check for active background jobs (Rebalance, etc.)
        cur.execute("SELECT count(*) FROM crdb_internal.jobs WHERE status = 'running';")
        running_jobs = cur.fetchone()[0]

        if under_rep == 0: # and running_jobs == 0:
            print("\n✅ Cluster is stable: All ranges have full replicas.") # and no jobs running.")
            break
        
        print(f"Waiting for stability: {under_rep} under-replicated, {running_jobs} jobs running...", end='\r')
        time.sleep(5)
    else:
        print("\n⚠️ Timeout reached: Cluster may still be rebalancing in the background.")

    cur.close()
    conn.close()

def main():
    parser = argparse.ArgumentParser(description="Manage a geodistributed CockroachDB cluster.")
    parser.add_argument('-c',  "--config", default="crdb/tu_cluster_crdb.json", choices=VALID_CONFIG_JSONS, help="Path to cluster JSON config")
    parser.add_argument('-a',  "--action", default="start", choices=VALID_ACTIONS, help="Start or Stop the cluster")
    parser.add_argument('-i',  "--image", default="omraz/seq_eval:crdb-custom", help="Docker image to use")
    parser.add_argument('-l',  "--license", default='crdb/crdb_license.json', help="Path to crdb_license.json")
    parser.add_argument('-u',  "--user", default=DEFAULT_USER, help="SSH user")
    parser.add_argument('-e',  "--env", default="st", help="Running environment (st/aws)")
    parser.add_argument('-w',  "--workload", default='ycsb', choices=['ycsb', 'tpcc'], help="Workload type for DB population")
    parser.add_argument('-p',  "--password", default=None, help="Password for SSH authentication (if needed)")
    parser.add_argument('-r',  "--robust", default=True, help="Use robust geo-partitioning (with cross-region replicas) instead of max performance. Only applicable for AWS env")
    parser.add_argument('-cp', "--cpus", default=16, help="No. of CPUs to allocate per server node")
    parser.add_argument('-me', "--memory", default=128, help="Memory (in GB) to allocate per server node")

    # Just for easy debugging in console
    '''
config = "crdb/tu_cluster_crdb.json"
action = "start"
image = "omraz/seq_eval:crdb-custom"
license_path = "crdb/crdb_license.json"
user = "omraz"
env = "st"
workload = "ycsb"
password = None
robust_mode = True
cpus = 16
memory = 128
    '''

    args = parser.parse_args()
    config = args.config
    action = args.action
    image = args.image
    license_path = args.license
    user = args.user
    env = args.env
    workload = args.workload
    password = args.password
    robust_mode = args.robust
    cpus = args.cpus
    memory = args.memory

    with open(config) as f:
        cluster_config = json.load(f)

    all_ips = []
    for region in cluster_config:
        all_ips += cluster_config[region]
    primary_ip = all_ips[0]
    regions = list(cluster_config.keys())
    primary_region = list(cluster_config.keys())[0]

    if action == "stop":
        stop_cluster_parallel(all_ips, user, password=password)
    elif action == "start":
        start_cluster_parallel(all_ips, cluster_config, image, user, env, cpus=cpus, memory=memory)
        initialize_and_setup_cluster(primary_ip, license_path, env, user=user, regions=regions, primary_region=primary_region)
        populate_db_tables(all_ips=all_ips, primary_ip=primary_ip, workload=workload, env=env, regions_list=regions, robust_mode=robust_mode, user=user)
        # Final safety check before handing off to the C++ benchmark
        if workload == 'ycsb':
            wait_for_cluster_ready(primary_ip)
    elif action == "populate":
        populate_db_tables(all_ips=all_ips, primary_ip=primary_ip, workload=workload, env=env, regions_list=regions, robust_mode=robust_mode, user=user)
        # Final safety check before handing off to the C++ benchmark
        if workload == 'ycsb':
            wait_for_cluster_ready(primary_ip)
    elif action == "partition":
        if workload != 'tpcc':
            print("Partitioning logic is currently only implemented for TPC-C. Please specify --workload tpcc to use this action.")
            return
        apply_tpcc_geo_partitioning(primary_ip, regions, warehouse_count=TPCC_WAREHOUSE_COUNT, user=user, env=env, robust_mode=robust_mode)
        apply_tpcc_index_partitioning(primary_ip, regions, warehouse_count=TPCC_WAREHOUSE_COUNT, user=user, env=env, robust_mode=robust_mode)
    else:
        print("Invalid action specified.")

if __name__ == "__main__":
    main()
