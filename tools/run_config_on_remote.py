import time
import os
import subprocess as sp
import shutil
import argparse
import math
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import simulate_network
import pps.simulate_regions as simulate_regions

VALID_SCENARIOS = ['baseline', 'skew', 'scalability', 'network', 'packet_loss', 'sunflower', 'lat_breakdown', 'vary_hw', 'server_skew', 'fault_tolerance']
VALID_WORKLOADS = ['ycsb', 'tpcc', 'movr', 'movie', 'pps', 'dsh', 'smallbank']
VALID_DATABASES = ['Detock', 'ddr_ts', 'ddr_only', 'slog', 'calvin', 'janus', 'crdb']
VALID_ENVIRONMENTS = ['local', 'st', 'aws']
VALID_IMAGES = ['omraz/oltp_survey:detock', 'omraz/seq_eval:crdb_benchmark']

parser = argparse.ArgumentParser(description="Run Detock experiment with a given scenario.")
parser.add_argument('-s',  '--scenario', default='scalability', choices=VALID_SCENARIOS, help='Type of experiment scenario to run (default: baseline)')
parser.add_argument('-w',  '--workload', default='tpcc', choices=VALID_WORKLOADS, help='Workload to run (default: ycsb)')
parser.add_argument('-e',  '--environment', default='st', choices=VALID_ENVIRONMENTS, help='What type of machine the experiment was run on.')
parser.add_argument('-c',  '--conf', default='examples/tpcc/tu_cluster_tpcc_ddr_ts.conf', help='.conf file used for experiment')
parser.add_argument('-i',  '--img', default='omraz/oltp_survey:detock', help='The Docker image of your built Detock system')
parser.add_argument('-d',  '--duration', default=60, help='Duration (in seconds) of a single experiment')
parser.add_argument('-dr', '--dry_run', default=False, help='Whether to run this as a dry run')
parser.add_argument('-u',  '--user', default="omraz", help='Username when logging into a remote machine')
parser.add_argument('-m',  '--machine', default="st5", help='The machine from which this script is (used to write out the scp command for collecting the results.)')
parser.add_argument(       '--clients', default=3000, help='Number of clients to use for a client machine')
parser.add_argument('-g',  '--generators', default=1, help='Number of generators to use for a client machine')
parser.add_argument('-tt', '--trial_tag', default="", help='Tag for differentiating between trials done with the same scenario (data will be collected to data/{workload}/{scenario}/{trial_tag}/{system}/{x_val})')
parser.add_argument('-db', '--database', default='Detock', choices=VALID_DATABASES, help='The database to test')
parser.add_argument('-bl', '--baseline_latencies', default=True, help='Whether to add baseline latencies to the experiments. Note: only works for full AWS experiments!')

args = parser.parse_args()
scenario = args.scenario
workload = args.workload
environment = args.environment
conf = args.conf
image = args.img
duration = args.duration
dry_run = args.dry_run
user = args.user
machine = args.machine
generators = args.generators
trial_tag = args.trial_tag
benchmark_container = f"{user}_benchmark"
server_container = f"{user}_slog"
database = args.database
baseline_latencies = args.baseline_latencies

if database == 'crdb':
    benchmark_container = "crdb-client"
    server_container = "crdb-node"

print(f"Running scenario: '{scenario}', workload: '{workload}', and trial tag: '{trial_tag}'")

BASIC_IFTOP_CMD = 'iftop 2>&1'
DEFAULT_DELAY_INTER_REGION = "65ms" # Corresponds to the us-west-1 <-> eu-west-1 connection on AWS
DEFAULT_JITTER_INTER_REGION = "3ms" # Corresponds to the us-west-1 <-> eu-west-1 connection on AWS

interfaces = {}

detock_dir = os.path.expanduser("~/Detock")
systems_to_test = [database]
short_benchmark_log = "benchmark_cmd.log"
log_dir = "data/{}/raw_logs"
cur_log_dir = None

if workload == 'ycsb':
    multi_partition_settings = 'mp=50,'
elif workload == 'tpcc':
    multi_partition_settings = ''
elif workload == 'movr':
    multi_partition_settings = ''
elif workload == 'pps':
    multi_partition_settings = 'mp=50,'
elif workload == 'movie':
    multi_partition_settings = "mp=50,"
elif workload == 'dsh':
    multi_partition_settings = "mp=50,"
elif workload == 'smallbank':
    multi_partition_settings = "mp=50,"
else:
    raise Exception(f"Multipartition settings not defined for workload {workload}")

if workload == 'ycsb':
    if database == 'Detock':
        clients = 1000
    elif database == 'slog':
        clients = 1000
    elif database == 'calvin':
        clients = 2500
    elif database == 'janus':
        clients = 1000
    elif database == 'crdb':
        clients = 400
    if scenario == 'baseline':
        benchmark_params = "\"mh={},mp=50\""
        x_vals = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    elif scenario == 'skew':
        benchmark_params = "\"mh=50,mp=50,hot={}\""
        x_vals = [1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250]
        if database == 'crdb':
            benchmark_params = "\"mh=50,mp=50,skew={}\""
            x_vals = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99, 0.999, 0.9999, 1.0]
    elif scenario == 'scalability':
        benchmark_params = "\"mh=50,mp=50\""
        clients = None
        x_vals = [1, 10, 100, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000]
        if database == 'crdb':
            x_vals = [1, 10, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 2500, 5000, 10_000, 25_000]
    elif scenario == 'network':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 10, 50, 100, 250, 500, 1000]
    elif scenario == 'packet_loss':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 0.1, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
    # For the latency breakdown, vary HW, server skew, and fault_tolerance we just run the vanilla workload
    elif scenario == 'lat_breakdown' or scenario == 'vary_hw' or scenario == 'fault_tolerance':
        benchmark_params = "\"mh={},mp=50\""
        x_vals = [50]
    elif scenario == 'server_skew':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = ["balanced", "us-west+", "us-west+_eu-west+", "us-west++", "us-west++_eu-west++", "us-west_only"]
    elif scenario == 'sunflower':
        benchmark_params = "\"mh=50,mp=50\""
        clients = None
        # TODO: Adjust the number of clients here. (Test how high they can go while maintaining an equal split)
        x_vals = ["700,2300", "800,2200", "900,2100", "1000,2000", "1100,1900", "1200,1800", "1300,1700", "1400,1600", "1500,1500",
                  "1600,1400", "1700,1300", "1800,1200", "1900,1100", "2000,1000", "2100,900", "2200,800", "2300,700"]
    else:
        raise Exception(f"Scenario {scenario} not implemented for workload {workload}")
    if database == 'crdb':
        single_benchmark_cmd = "python3 crdb/admin.py -a benchmark --image {image} -co {conf} -u {user} --txns 2000000 --seed 1 --clients {clients} --duration {duration} -wl ycsb --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
    else:
        single_benchmark_cmd = "python3 tools/admin.py benchmark --image {image} {conf} -u {user} --txns 2000000 --seed 1 --clients {clients} --generators {generators} --duration {duration} -wl basic --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
elif workload == 'tpcc':
    if database == 'Detock':
        clients = 500
    elif database == 'slog':
        clients = 500
    elif database == 'calvin':
        clients = 1000
    elif database == 'janus':
        clients = 1000
    elif database == 'crdb':
        clients = -1 # TODO: Figure out the right number of clients for CRDB TPCC experiments
    if scenario == 'baseline':
        benchmark_params = "\"rem_item_prob={},rem_payment_prob={}\""
        x_vals = [0.0, 0.01, 0.02, 0.05, 0.075, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0]
        # Note: For CRDB, we must do this manually.
        # For 0% MH/FSH, just run with --local-warehouses. For higher values, CRDB needs to be recompiled changing the respective hard-coded value
        # nano pkg/workload/tpcc/payment.go      (search for 'IntN(')
        # nano pkg/workload/tpcc/new_order.go
    elif scenario == 'skew':
        benchmark_params = "\"skew={}\""
        x_vals = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        if database == 'crdb':
            benchmark_params = "\"active={}\""
            x_vals = [1, 10, 50, 100, 250, 500, 750, 1000, 1200]
    elif scenario == 'scalability':
        benchmark_params = "\"\""
        clients = None
        x_vals = [1, 10, 100, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000]
        if database == 'crdb':
            x_vals = [1, 10, 25, 50, 100, 250, 500, 1000, 1200]
    elif scenario == 'network':
        benchmark_params = "\"\""
        x_vals = [0, 10, 50, 100, 250, 500, 1000]
    elif scenario == 'packet_loss':
        benchmark_params = "\"\""
        x_vals = [0, 0.1, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
    elif scenario == 'lat_breakdown' or scenario == 'vary_hw' or scenario == 'fault_tolerance':
        benchmark_params = "\"rem_item_prob={},rem_payment_prob={}\""
        x_vals = [0.01]
    elif scenario == 'server_skew':
        benchmark_params = "\"\""
        x_vals = ["balanced", "us-west+", "us-west+_eu-west+", "us-west++", "us-west++_eu-west++", "us-west_only"]
    elif scenario == 'sunflower':
        benchmark_params = "\"\""
        clients = None
        # TODO: Adjust the number of clients here. (Test how high they can go while maintaining an equal split)
        x_vals = ["700,2300", "800,2200", "900,2100", "1000,2000", "1100,1900", "1200,1800", "1300,1700", "1400,1600", "1500,1500",
                  "1600,1400", "1700,1300", "1800,1200", "1900,1100", "2000,1000", "2100,900", "2200,800", "2300,700"]
    else:
        raise Exception(f"Scenario {scenario} not implemented for workload {workload}")
    if database == 'crdb':
        single_benchmark_cmd = "python3 crdb/admin.py -a benchmark --image {image} -co {conf} -u {user} --txns 2000000 --seed 1 --clients {clients} --duration {duration} -wl tpcc -sc {scenario} --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
    else:
        single_benchmark_cmd = "python3 tools/admin.py benchmark --image {image} {conf} -u {user} --txns 2000000 --seed 1 --clients {clients} --generators {generators} --duration {duration} -wl tpcc --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
elif workload == 'dsh':
    if database == 'Detock':
        clients = 500
    elif database == 'slog':
        clients = 500
    elif database == 'calvin':
        clients = 200
    elif database == 'janus':
        clients = 2500
    elif database == 'crdb':
        clients = -1 # TODO:Figure out the right number of clients for CRDB DSH experiments
    if scenario == 'baseline':
        benchmark_params = "\"mh={},mp=.25\""
        x_vals = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    elif scenario == 'skew':
        benchmark_params = "\"mh=.25,mp=.25,hot_chance=.9,hot={}\""
        x_vals = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99]
    elif scenario == 'scalability':
        benchmark_params = "\"mh=.25,mp=.25\""
        clients = None
        x_vals = [1, 10, 100, 200, 250, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000]
    elif scenario == 'network':
        benchmark_params = "\"mh=.25,mp=.25\""
        x_vals = [0, 10, 50, 100, 250, 500, 1000]
    elif scenario == 'packet_loss':
        benchmark_params = "\"mh=.25,mp=.25\""
        x_vals = [0, 0.1, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
    #elif scenario == 'sunflower':
    #    benchmark_params = "\"mh=.25,mp=.25,sf=/opt/slog/dsh/flower-{}.csv,duration=2000000\""
    #    x_vals = [0.5, 0.65, 0.85, 1.0]
    elif scenario == 'lat_breakdown' or scenario == 'vary_hw' or scenario == 'fault_tolerance':
        benchmark_params = "\"mh={},mp=.25\""
        x_vals = [0.25]
    elif scenario == 'sunflower':
        benchmark_params = "\"mh=.25,mp=.25\""
        clients = None
        # TODO: Adjust the number of clients here. (Test how high they can go while maintaining an equal split)
        x_vals = ["700,2300", "800,2200", "900,2100", "1000,2000", "1100,1900", "1200,1800", "1300,1700", "1400,1600", "1500,1500",
                  "1600,1400", "1700,1300", "1800,1200", "1900,1100", "2000,1000", "2100,900", "2200,800", "2300,700"]
    else:
        raise Exception(f"Scenario {scenario} not implemented for workload {workload}")
    single_benchmark_cmd = "python3 tools/admin.py benchmark --image {image} {conf} -u {user} --txns 2000000 --seed 1 --clients {clients} --generators {generators} --duration {duration} -wl dsh --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
elif workload == 'movie':
    if database == 'Detock':
        clients = 2500
    elif database == 'slog':
        clients = 2500
    elif database == 'calvin':
        clients = 500
    elif database == 'janus':
        clients = 1000
    elif database == 'crdb':
        clients = -1 # TODO:Figure out the right number of clients for CRDB Movie experiments
    if scenario == 'baseline':
        benchmark_params = "\"mh={},mp=50\""
        x_vals = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    elif scenario == 'skew':
        benchmark_params = "\"mh=50,mp=50,skew={}\""
        x_vals = [0, 0.01, 0.1, 0.2, 0.5, 1]
    elif scenario == 'scalability':
        benchmark_params = "\"mh=50,mp=50\""
        clients = None
        x_vals = [1, 10, 100, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000]
    elif scenario == 'network':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 10, 50, 100, 250, 500, 1000]
    elif scenario == 'packet_loss':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 0.1, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
    elif scenario == 'lat_breakdown' or scenario == 'vary_hw' or scenario == 'fault_tolerance':
        benchmark_params = "\"mh={},mp=50\"" 
        x_vals = [50]
    elif scenario == 'sunflower':
        benchmark_params = "\"mh=50,mp=50\""
        clients = None
        # TODO: Adjust the number of clients here. (Test how high they can go while maintaining an equal split)
        x_vals = ["700,2300", "800,2200", "900,2100", "1000,2000", "1100,1900", "1200,1800", "1300,1700", "1400,1600", "1500,1500",
                  "1600,1400", "1700,1300", "1800,1200", "1900,1100", "2000,1000", "2100,900", "2200,800", "2300,700"]
    #elif scenario == 'sunflower':
    #    benchmark_params = "\"mh=50,mp=50,sunflower=1,sf_fraction={},sf_home=0\""
    #    x_vals = [0.6, 0.8, 0.9, 0.95, 1]
    else:
        raise Exception(f"Scenario {scenario} not implemented for workload {workload}")
    single_benchmark_cmd = "python3 tools/admin.py benchmark --image {image} {conf} -u {user} --txns 2000000 --seed 1 --clients {clients} --generators {generators} --duration {duration} -wl movie --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
elif workload == 'movr':
    if scenario == 'baseline':
        benchmark_params = "\"mh={},mp=50\""
        x_vals = [0, 20, 40, 60, 80, 100]
    elif scenario == 'skew':
        benchmark_params = "\"mh=50,mp=50,skew={}\""
        x_vals = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    elif scenario == 'scalability':
        benchmark_params = "\"mh=50,mp=50\""
        clients = None
        x_vals = [1, 10, 100, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000]
    elif scenario == 'network':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 10, 50, 100, 250, 500, 1000]
    elif scenario == 'packet_loss':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 0.1, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
    #elif scenario == 'sunflower':
    #    benchmark_params = "\"mh=50,mp=50,sunflower-falloff={},sunflower-max=40,sunflower-cycles=1\""
    #    x_vals = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    elif scenario == 'lat_breakdown' or scenario == 'vary_hw' or scenario == 'fault_tolerance':
        benchmark_params = "\"mh={},mp={}\""
        x_vals = [50]
    elif scenario == 'sunflower':
        benchmark_params = "\"mh=50,mp=50\""
        clients = None
        # TODO: Adjust the number of clients here. (Test how high they can go while maintaining an equal split)
        x_vals = ["700,2300", "800,2200", "900,2100", "1000,2000", "1100,1900", "1200,1800", "1300,1700", "1400,1600", "1500,1500",
                  "1600,1400", "1700,1300", "1800,1200", "1900,1100", "2000,1000", "2100,900", "2200,800", "2300,700"]
    else:
        raise Exception(f"Scenario {scenario} not implemented for workload {workload}")
    single_benchmark_cmd = "python3 tools/admin.py benchmark --image {image} {conf} -u {user} --txns 2000000 --seed 1 --clients {clients} --generators {generators} --duration {duration} -wl movr --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
elif workload == 'pps':
    if database == 'Detock':
        clients = 1600
    elif database == 'slog':
        clients = 1300
    elif database == 'calvin':
        clients = 600
    elif database == 'janus':
        clients = 4000
    elif database == 'crdb':
        clients = -1 # TODO:Figure out the right number of clients for CRDB PPS experiments
    if scenario == 'baseline':
        benchmark_params = "\"mh={},mp=50,nearest=1\""
        x_vals = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    elif scenario == 'skew':
        benchmark_params = "\"mh=50,mp=50,nearest=1,hot={}\""
        x_vals = [0, 0.0001, 0.001, 0.01, 0.1, 0.5, 1.0]
    elif scenario == 'scalability':
        benchmark_params = "\"mh=50,mp=50,nearest=1\""
        clients = None
        x_vals = [1, 10, 100, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000, 2500, 3000, 4000, 5000, 7500, 10_000, 25_000, 50_000, 100_000] 
    elif scenario == 'network':
        benchmark_params = "\"mh=50,mp=50,nearest=1\""
        x_vals = [0, 10, 50, 100, 250, 500, 1000]
    elif scenario == 'packet_loss':
        benchmark_params = "\"mh=50,mp=50,nearest=1\""
        x_vals = [0, 0.1, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
    elif scenario == 'lat_breakdown' or scenario == 'vary_hw' or scenario == 'fault_tolerance':
        benchmark_params = "\"mh={},mp=50,nearest=1\""
        x_vals = [50]
    elif scenario == 'sunflower':
        benchmark_params = "\"mh=50,mp=50,nearest=1,mix=80:8:8:2:2\""
        clients = None
        x_vals = ["700,2300", "800,2200", "900,2100", "1000,2000", "1100,1900", "1200,1800", "1300,1700", "1400,1600", "1500,1500",
                  "1600,1400", "1700,1300", "1800,1200", "1900,1100", "2000,1000", "2100,900", "2200,800", "2300,700"]
    else:
        raise Exception(f"Scenario {scenario} not implemented for workload {workload}")
    single_benchmark_cmd = "python3 tools/admin.py benchmark --image {image} {conf} -u {user} --txns 0 --seed 1 --clients {clients} --generators {generators} --duration {duration} -wl pps --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
elif workload == 'smallbank':
    if scenario == 'baseline':
        benchmark_params = "\"mh={},mp=50\""
        x_vals = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    elif scenario == 'skew':
        benchmark_params = "\"mh=50,mp=50,hot={}\""
        x_vals = [0, 0.0001, 0.001, 0.01, 0.1, 0.5, 1.0]
    elif scenario == 'scalability':
        benchmark_params = "\"mh=50,mp=50\""
        clients = None
        x_vals = [1, 10, 100, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000]
    elif scenario == 'network':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 10, 50, 100, 250, 500, 1000]
    elif scenario == 'packet_loss':
        benchmark_params = "\"mh=50,mp=50\""
        x_vals = [0, 0.1, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
    elif scenario == 'lat_breakdown' or scenario == 'vary_hw' or scenario == 'fault_tolerance':
        benchmark_params = "\"mh={},mp=50\""
        x_vals = [50]
    elif scenario == 'sunflower':
        benchmark_params = "\"mh={},mp=50,sunflower_target_regions=0:0:0:0:0:0:0:0:0:0:0:0,sunflower_target_probabilities=0:10:20:30:40:50:60:70:80:90:100:100\""
        x_vals = [50]
    else:
        raise Exception(f"Scenario {scenario} not implemented for workload {workload}")
    single_benchmark_cmd = "python3 tools/admin.py benchmark --image {image} {conf} -u {user} --txns 0 --seed 1 --clients {clients} --generators {generators} --duration {duration} -wl smallbank --param {benchmark_params} 2>&1 | tee {short_benchmark_log}"
else:
    raise Exception(f"Workload {workload} not implemented")

if database == 'crdb':
    collect_client_cmd = "python3 crdb/admin.py -a collect_client -u {user} --config {conf} --out-dir data --tag {tag} --workload {workload}"
else:
    collect_client_cmd = "python3 tools/admin.py collect_client -u {user} --config {conf} --out-dir data --tag {tag}"

def run_subprocess(cmd, dry_run=False):
    if dry_run:
        print(f"Would have run command: {cmd}")
        return True
    else:
        return sp.run(cmd, shell=True, capture_output=True, text=True)

def get_server_ips_from_conf(conf_path):
    with open(conf_path, "r") as f:
        conf_data = f.readlines()
    ips_used = set()
    for line in conf_data:
        if '    addresses: ' in line:
            ips_used.add(line.split('    addresses: "')[1].split('"')[0])
    ips_used = list(ips_used)
    return ips_used

def get_client_ips_from_conf(conf_path):
    with open(conf_path, "r") as f:
        conf_data = f.readlines()
    ips_used = set()
    for line in conf_data:
        if '    client_addresses: ' in line:
            ips_used.add(line.split('    client_addresses: "')[1].split('"')[0])
    ips_used = list(ips_used)
    return ips_used

def get_all_ips_from_conf(conf_path):
    with open(conf_path, "r") as f:
        conf_data = f.readlines()
    # Using a set will avoid duplicates on the ST cluster
    ips_used = []
    for line in conf_data:
        if '    client_addresses: ' in line:
            cur_ip = line.split('    client_addresses: "')[1].split('"')[0]
            if cur_ip not in ips_used:
                ips_used.append(cur_ip)
        elif '    addresses: ' in line:
            cur_ip = line.split('    addresses: "')[1].split('"')[0]
            if cur_ip not in ips_used:
                ips_used.append(cur_ip)
    ips_used = list(dict.fromkeys(ips_used))
    return list(ips_used)

def get_num_partitions_from_conf(conf_path):
    with open(conf_path, "r") as f:
        conf_data = f.readlines()
    num_partitions = -1
    for line in conf_data:
        if 'num_partitions: ' in line:
            num_partitions = int(line.split('num_partitions: ')[1])
    return num_partitions

def get_network_interfaces(ips_used):
    interface = run_subprocess(BASIC_IFTOP_CMD).stdout.split('\n')[0].split('interface: ')[1]
    print(f"This machine uses the network interface: {interface}")
    for ip in ips_used:
        try:
            ssh_target = f"{user}@{ip}" if user else ip
            ssh_cmd = f"ssh {ssh_target} '{BASIC_IFTOP_CMD}'"
            result = run_subprocess(ssh_cmd, dry_run)
            cur_interface = result.stdout.split('\n')[0].split('interface: ')[1]
            print(f"IP {ip} uses interface {cur_interface}")
            interfaces[ip] = cur_interface
        except:
            print(f"Unable to find interface for IP: {ip}")

def start_net_monitor(user, interfaces):
    for ip, iface in interfaces.items():  # assuming interfaces is a dict {ip: interface}
        # Note, we prepare monitoring for both tansfer and receive, but only log transfer (tx) for now
        # Received causes problems (only logs ever 3? seconds)
        cmd = (
            f"ssh {user}@{ip} '"
            f"echo \"timestamp_ms,bytes_sent\" > net_traffic.csv; "
            f"prev_rx=$(awk '\\''$1 ~ \"{iface}:\" {{print $2}}'\\'' /proc/net/dev); "
            f"prev_tx=$(awk '\\''$1 ~ \"{iface}:\" {{print $10}}'\\'' /proc/net/dev); "
            f"while true; do "
            f"sleep 1; "
            f"now=$(date +%s%3N); "
            f"curr_rx=$(awk '\\''$1 ~ \"{iface}:\" {{print $2}}'\\'' /proc/net/dev); "
            f"curr_tx=$(awk '\\''$1 ~ \"{iface}:\" {{print $10}}'\\'' /proc/net/dev); "
            f"delta_rx=$((curr_rx - prev_rx)); "
            f"delta_tx=$((curr_tx - prev_tx)); "
            f"echo \"$now,$delta_tx\" >> net_traffic.csv; "
            f"prev_tx=$curr_tx; "
            f"done' > /dev/null 2>&1 &"
        )
        result = sp.run(cmd, shell=True)
        if hasattr(result, "returncode") and result.returncode != 0:
            print(f"Launch network monitoring command in ip '{ip}' failed with exit code {result.returncode}!")
    print("Started network monitoring on all server ips")

def stop_and_collect_network_monitor(user, interfaces, cur_log_dir):
    for ip in interfaces.keys():
        sp.run(f"ssh {user}@{ip} pkill -f net_traffic.csv", shell=True)
        result = sp.run(f"scp {user}@{ip}:net_traffic.csv {cur_log_dir}/net_traffic_{ip.replace('.', '_')}.csv", shell=True)
        if hasattr(result, "returncode") and result.returncode != 0:
            print(f"Collecting network monitoring command failed with exit code {result.returncode}!")
            break

def start_resource_monitor(user, ips_used, env='aws'):
    if env == 'aws':
        container_name = "slog"
    else:
        container_name = f"{user}_slog"
    if database == 'crdb':
        container_name = "crdb-node"
    for ip in ips_used:
        # We get the CPU, Memory and Disk utilization percentages here
        # We use start_net_monitor for network monitoring
        cmd = (
            f"ssh {user}@{ip} '"
            f"echo \"timestamp_ms,cpu_pct,mem_pct,disk_util_pct\" > resource_util.csv; "
            f"while true; do "
            f"sleep 1; "
            f"now=$(date +%s%3N); "
            # CPU % for the container
            f"cpu_pct=$(docker stats --no-stream --format \"{{{{.CPUPerc}}}}\" {container_name} | tr -d '%'); "
            # Memory % for the container
            f"mem_pct=$(docker stats --no-stream --format \"{{{{.MemPerc}}}}\" {container_name} | tr -d '%'); "
            # Disk util %
            f"disk_util_pct=$(iostat -dx 1 2 | "
            f"awk '\\''$1 ~ /^nvme|^sd/ {{print $12; exit}}'\\''); "
            # Log results
            f"echo \"$now,$cpu_pct,$mem_pct,$disk_util_pct\" >> resource_util.csv; "
            f"done' > /dev/null 2>&1 &"
        )
        result = sp.run(cmd, shell=True)
        if hasattr(result, "returncode") and result.returncode != 0:
            print(f"Launch resource monitor on ip '{ip}' failed with exit code {result.returncode}!")
    print("Started resource monitoring (CPU %, Mem %, Disk %) on all server IPs")

def stop_and_collect_resource_monitor(user, ips_used, cur_log_dir):
    for ip in ips_used:
        sp.run(f"ssh {user}@{ip} pkill -f resource_util.csv", shell=True)
        result = sp.run(
            f"scp {user}@{ip}:resource_util.csv "
            f"{cur_log_dir}/resource_util_{ip.replace('.', '_')}.csv",
            shell=True
        )
        if hasattr(result, "returncode") and result.returncode != 0:
            print(f"Collecting resource monitoring output failed on {ip}!")
            break

# Helper function to check if the database finished preloading all rows before we actually start the experiment
def check_table_loading_finished(ips, workload, conf_path):
    for ip in ips:
        print(f"Checking readiness on server on IP {ip}...")
        try:
            ssh_target = f"{user}@{ip}" if user else ip
            server_container_cmd = f'docker container logs {server_container} 2>&1'
            ssh_cmd = f"ssh {ssh_target} '{server_container_cmd}'"
            result = run_subprocess(ssh_cmd, dry_run)
            if not 'Bound Server to: ' in result.stdout:
                return False
        except:
            print(f"Unable to check loading status for IP: {ip}")
    return True

def apply_baseline_latencies(interfaces, user, all_ips_used, latency_file, std_file, extra_latency=0, extra_packet_loss=0):
    print("Applying baseline latencies....")
    latency_matrix = pd.read_csv(latency_file, header=0, index_col=0)
    latency_std = pd.read_csv(std_file, header=0, index_col=0)
    latency_matrix += extra_latency
    jitter_matrix = (0 * latency_matrix) + extra_latency/10 # For the 'network' scenario, we also add more jitter (10% of the extra added latency)
    jitter_matrix += latency_std # We will always have at least the jitter from the default latencies
    num_partitions = get_num_partitions_from_conf(conf)
    if environment == 'aws':
        num_partitions += 1 # On the AWS setup we also have a separate machine for the client, on ST they are collocated
    num_regions = int(len(all_ips_used) / num_partitions)
    def single_source_latency_task(i):
        cur_region = math.floor(i/num_partitions)
        cur_latencies = latency_matrix[latency_matrix.columns[cur_region]]
        cur_jitters = jitter_matrix[jitter_matrix.columns[cur_region]]
        ssh_target = f"{user}@{all_ips_used[i]}"
        interface = interfaces[all_ips_used[i]]
        # reset qdisc on remote
        sp.run(["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", ssh_target, f"sudo tc qdisc del dev {interface} root || true"], check=False)
        sp.run(["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", ssh_target, f"sudo tc qdisc add dev {interface} root handle 1: htb"], check=True)
        for j in range(num_regions):
            # Since we apply everything in 2 directions, half the applied values
            cur_delay = f'{cur_latencies[j] / 2}ms'
            cur_jitter = f'{cur_jitters[j] / 2}ms'
            cur_packet_loss = f'{extra_packet_loss / 2}%'
            target_region_ips = all_ips_used[num_partitions*j:num_partitions*(j+1)]
            class_handle_idx = j+1
            simulate_network.apply_netem_to_region(source_ip=all_ips_used[i], user=user, interface=interface, delay=cur_delay, jitter=cur_jitter, loss=cur_packet_loss, ips=target_region_ips, idx=class_handle_idx)
    # Setup all latencies concurrently
    with ThreadPoolExecutor() as executor:
        executor.map(single_source_latency_task, range(len(all_ips_used)))

ips_used = get_server_ips_from_conf(conf_path=conf)
client_ips_used = get_client_ips_from_conf(conf_path=conf)
all_ips_used = get_all_ips_from_conf(conf_path=conf)
print(f"The IPs used in this experiment are: {ips_used}")
get_network_interfaces(ips_used=ips_used)

# Check that all network emulation settings are switched off
print("-------------------------------------------------------------------")
print("Removing any leftover network settings from previous experiments .....")
print("It's ok if the following removals fail. It's only a safeguard in case there were unremoved network settings from before.")
print()
simulate_network.remove_netem(ips=interfaces, user=user)
print("-------------------------------------------------------------------")
print()

if database != 'crdb':
    while not check_table_loading_finished(ips_used, workload, conf):
        time.sleep(10)
print("All tables pre-loaded")

if baseline_latencies and scenario != 'server_skew':
    if environment == 'aws':
        latency_file = 'plots/data/aws/rtt_matrix_aws_regions.csv'
        std_file = 'plots/data/aws/rtt_std_matrix_aws_regions.csv'
    elif environment == 'st':
        latency_file = 'plots/data/st/rtt_matrix_st_simulation.csv'
        std_file = 'plots/data/st/rtt_std_matrix_st_simulation.csv'
    else:
        raise Exception(f"Baseline latencies not supported for environment {environment}")

    # This needs to be fixed for ST setup
    #apply_baseline_latencies(interfaces=interfaces, user=user, all_ips_used=all_ips_used, latency_file=latency_file, std_file=std_file)

    simulate_regions.apply_all_delays(user=user, interfaces=interfaces, inter_region_delay=DEFAULT_DELAY_INTER_REGION, inter_region_jitter=DEFAULT_JITTER_INTER_REGION)

scenario_folder = f'data/{workload}/{scenario}' if trial_tag == "" else f'data/{workload}/{scenario}/{trial_tag}'
os.makedirs(scenario_folder, exist_ok=True)
tags = []
for system in systems_to_test:
    print("#####################")
    print(f"Testing system: {system} with x_vals: {x_vals}")
    systems_folder = f'{scenario_folder}/{system}'
    os.makedirs(systems_folder, exist_ok=True)
    # Run the benchmark for all x_vals and collect all results
    for x_val in x_vals:
        print("---------------------")
        print(f"Running experiment with x_val: {x_val}")
        tag = None
        cur_benchmark_params = benchmark_params.format(x_val, x_val) # Works for: baseline, skew, scalability, network, packet_loss
        cur_clients = clients if clients is not None else x_val
        cur_benchmark_cmd = single_benchmark_cmd.format(image=image, conf=conf, user=user, clients=cur_clients, generators=generators, duration=duration, benchmark_params=cur_benchmark_params, short_benchmark_log=short_benchmark_log, scenario=scenario)
        print(f"\n>>> Running: {cur_benchmark_cmd}")
        if scenario == 'network':
            # Emulate the network conditions first
            # Since the slowdown is applied in both directions, we divide by 2
            delay = f"{int(x_val / 2)}ms"
            jitter = f"{int(x_val / 10 / 2)}ms"
            loss = "0%"
        elif scenario == 'packet_loss':
            delay = "0ms"
            jitter = "0ms"
            loss = f"{x_val}%"
        elif scenario == 'server_skew':
            latency_file = f"tools/server_skew_rtts/{x_val}.csv"
            apply_baseline_latencies(interfaces=interfaces, user=user, all_ips_used=all_ips_used, latency_file=latency_file, std_file=std_file)
        # Note: the netem command may require allowing passwordless sudo for tc commands
        # I.e., add something like 'omraz ALL=(ALL) NOPASSWD: /usr/sbin/tc' to 'sudo visudo'
        if scenario == 'network':
            ### OLD METHOD (applies same settings to all servers, not per-region) ###
            #simulate_network.apply_netem(delay=delay, jitter=jitter, loss=loss, ips=interfaces, user=user)
            ### NEW METHOD (applies per-region settings based on baseline latencies) ###
            simulate_regions.apply_all_delays(user=user, interfaces=interfaces, inter_region_delay=delay, inter_region_jitter=jitter)
            print(f"All servers simulating an additional inter-region delay of {delay} and jitter of {jitter}")
        if scenario == 'packet_loss':
            simulate_network.apply_netem(delay=delay, jitter=jitter, loss=loss, ips=interfaces, user=user)
            print(f"All servers simulating an additional packet loss of {loss}")
        # End any leftover monitoring, and start a new monitoring of the outbound traffic on remote machines
        for ip in interfaces.keys():
            sp.run(f"ssh {user}@{ip} pkill -f net_traffic.csv", shell=True)
        start_net_monitor(user=user, interfaces=interfaces)
        start_resource_monitor(user=user, ips_used=ips_used, env=environment)
        # THE ACTUAL EXPERIMENT RUN
        print("Preparations done. Starting the benchmark now ....")
        result = run_subprocess(cur_benchmark_cmd, dry_run)
        # Print and collect output
        benchmark_cmd_log = ['']
        if not dry_run:
            print(result.stdout)
            print("[stderr]:", result.stderr)
            if result.returncode != 0:
                print(f"Benchmark command failed with exit code {result.returncode}!")
                #break
            # Get tag from benchmark cmd log
            benchmark_cmd_log = result.stdout.split('\n')
            for line in benchmark_cmd_log:
                if 'admin INFO: Tag: ' in line:
                    tag = line.split('admin INFO: Tag: ')[1]
                    break
        else:
            tag = 'dry_run'
        if tag is None:
            print(f"Unable to find tag in benchmark command output, aborting!")
            break
        tags.append(tag)
        cur_log_dir = log_dir.format(tag)
        # Make new (local) dir for storing result
        os.makedirs(cur_log_dir, exist_ok=True)
        # Store captured logs into file
        with open(f"{cur_log_dir}/{short_benchmark_log}", 'w') as f:
            for line in benchmark_cmd_log:
                f.write(f"{line}\n")
        # Remove any network restrictions
        if scenario == 'network' or scenario == 'packet_loss' or scenario == 'server_skew':
            # Remove emulated network conditions first
            simulate_network.remove_netem(ips=interfaces, user=user)
            print(f"Network settings on all servers back to normal!")
        # Collect the metrics from all clients
        result = run_subprocess(collect_client_cmd.format(user=user, conf=conf, tag=tag, workload=workload), dry_run)
        if hasattr(result, "returncode") and result.returncode != 0:
            print(f"collect_client command failed with exit code {result.returncode}!")
            break
        collect_benchmark_container_cmd = f"docker container logs {benchmark_container} 2>&1"
        # Collect logs from all the benchmark container (for throughput)
        client_count = 0
        for client in client_ips_used:
            log_file_name = f"data/{tag}/raw_logs/benchmark_container_{client.replace('.', '_')}.log"
            ssh_cmd = f"ssh {user}@{client} '{collect_benchmark_container_cmd}'"
            result = run_subprocess(ssh_cmd, dry_run)
            if hasattr(result, "returncode") and result.returncode != 0:
                print(f"collect_benchmark_container command failed with exit code {result.returncode}!")
                break
            with open(log_file_name, 'w') as f:
                if not dry_run:
                    for line in result.stdout.split('\n'):
                        f.write(f"{line}\n")
        stop_and_collect_network_monitor(user, interfaces, cur_log_dir)
        stop_and_collect_resource_monitor(user, ips_used, cur_log_dir)
        # Save '.conf' file that was used to set up the cluster & experiment and ips with their respective regions
        shutil.copyfile(conf, os.path.join(cur_log_dir, conf.split('/')[-1]))
        if machine in ["st1", "st2", "st3", "st5"]:
            ips_file = 'examples/st_ips.json'
        else:
            ips_file = 'aws/ips.json'
        shutil.copyfile(ips_file, os.path.join(cur_log_dir, 'ips.json'))
        # Move and rename the folder accordingly
        if scenario == 'lat_breakdown': # For the latency breakdown we anyway just have 1 x_val
            target_folder = systems_folder
        else:
            target_folder = f'{systems_folder}/{x_val}'
        if os.path.exists(target_folder): # We need to do this to make sure 'shutil.move()' doesn't just dump the folder inside the target folder if it already exists
            shutil.rmtree(target_folder)
        shutil.move(f'data/{tag}', target_folder)

# Clean up ~/data/{tag} on remote machines to save space
# This will not work, because some people don't have sudo. Also it (probably) prompts passwords.
'''print("Cleaning up remote data folders ....")
for client in client_ips_used:
    ssh_cmd = f"ssh {user}@{client} 'sudo rm -rf data/*'"
    result = run_subprocess(ssh_cmd, dry_run)'''

print("#####################")
zip_folder = f'{detock_dir}/{scenario_folder}'
zip_name = f'{scenario}_{trial_tag}' if trial_tag else scenario
print(f"\nAll {scenario} on {workload} experiments done (Trial: {trial_tag}). Zipping up files into {zip_folder}.zip ....")
shutil.make_archive(zip_folder, 'zip', zip_folder)
print("You can now copy over the logs with one of:")
print(f"scp -r {machine}:{zip_folder}/. plots/raw_data/{environment}/{workload}/{scenario}")
print(f"scp -r {machine}:{zip_folder}.zip plots/raw_data/{environment}/{workload}/{zip_name}.zip")
print("============================================")