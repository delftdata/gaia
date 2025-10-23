# SmallBank Partitioning

This folder contains the scripts and configurations used to generate benchmark tables and execute thesis-related experiments on the SmallBank benchmark across different geo-distributed database systems: **Detock**, **SLOG**, **Calvin**, and **Janus**.

## Cluster Setup

For general setup, Python environment installation, and detailed explanation of script parameters, please refer to the [tools/README.md](../../tools/README.md).

## Table Generation

The numbers of clients are taken as argument from the configuration files (e.g., `single.conf`).
The main transaction type of our workload is Balance. The transaction mix is defined as followed: Bal 40%, DC 25%, TS 15%, Amg 5%, WC 15%. 

## Inter-Region Delays
This script [here](../../tools/inter-region.py) configures network delay between partitions located in different regions to simulate inter-region latency in distributed experiments. It specifically sets a one-way delay of 50 ms, which results in an approximate 100 ms round-trip time between partitions residing in different regions.

Run the script with either apply or remove:
```bash
python inter-region.py apply   # Apply inter-region delays
python inter-region.py remove  # Remove inter-region delays
```

## Cluster
### Running a Complete Scenario
The complete instructions about setting up the Python environment and all the customizable parameters of the scripts can be found [here](../../tools/README.md).

We have the following available scenarios : baseline, skew, sunflower, scabaliblity, network, packet_loss

### (Calvin)
1. Spin up the cluster using the command: python3 tools/admin.py start --image USERNAME/detock-smallbank:latest  examples/smallbank/tu_cluster_smallbank_calvin.conf -u USERNAME -e GLOG_v=1 --bin slog
2. Run the scenario with the command: python3 tools/run_config_on_remote.py -s SCENARIO -w smallbank -u USERNAME -db calvin -c examples/smallbank/tu_cluster_smallbank_calvin.conf -i USERNAME/detock-smallbank:latest 
3. Copy the results to the `plots/` folder in the `raw_data/smallbank ` directory.
4. Create the plots using the command: python3 plots/extract_exp_results.py -s SCENARIO -w smallbank

### (SLOG)
1. Spin up the cluster using the command: python3 tools/admin.py start --image USERNAME/detock-smallbank:latest  examples/smallbank/tu_cluster_smallbank_slog.conf -u USERNAME -e GLOG_v=1 --bin slog
2. Run the scenario with the command: python3 tools/run_config_on_remote.py -s SCENARIO -w smallbank -u USERNAME -db slog -c examples/smallbank/tu_cluster_smallbank_slog.conf -i USERNAME/detock-smallbank:latest 
3. Copy the results to the `plots/` folder in the `raw_data/smallbank ` directory.
4. Create the plots using the command: python3 plots/extract_exp_results.py -s SCENARIO -w smallbank

### (DETOCK)
1. Spin up the cluster using the command:
python3 tools/admin.py start --image USERNAME/detock-smallbank:latest  examples/smallbank/tu_cluster_smallbank_detock.conf -u USERNAME -e GLOG_v=1 --bin slog
2. Run the scenario with the command: python3 tools/run_config_on_remote.py -s SCENARIO -w smallbank -u USERNAME  -c examples/smallbank/tu_cluster_smallbank_detock.conf -i USERNAME/detock-smallbank:latest 
3. Copy the results to the `plots/` folder in the `raw_data/smallbank ` directory.
4. Create the plots using the command: python3 plots/extract_exp_results.py -s SCENARIO -w smallbank

### (Janus)
1. Spin up the cluster using the command: python3 tools/admin.py start --image USERNAME/detock-smallbank:latest  examples/smallbank/tu_cluster_smallbank_janus.conf -u USERNAME -e GLOG_v=1 --bin janus
2. Run the scenario with the command: python3 tools/run_config_on_remote.py -s SCENARIO -w smallbank -u USERNAME -db janus -c examples/smallbank/tu_cluster_smallbank_janus.conf -i USERNAME/detock-smallbank:latest 
3. Copy the results to the `plots/` folder in the `raw_data/smallbank ` directory.
4. Create the plots using the command: python3 plots/extract_exp_results.py -s SCENARIO -w smallbank

