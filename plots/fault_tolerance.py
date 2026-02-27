import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as ticker
import argparse
import os
from os.path import join

parser = argparse.ArgumentParser(
        add_help=True,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

# In practice, we only use 'region_failure' and 'prime_node_failure'
VALID_EXPERIMENTS = ['region_failure', 'prime_node_failure', 'non_prime_node_failure', 'combined']
VALID_WORKLOADS = ['ycsb', 'tpcc']
VALID_ENVRONMENTS = ['st', 'aws']
VALID_SYSTEMS = ['crdb']
FAILURE_REGION = '0-0' # The region in which 1 or more nodes fail.
TPS_WINDOW_SIZE = 100 # Number of 100ms intervals to average over for the rolling average throughput plot (e.g., 20 intervals = 2s window)

# Experiemnts:
#
# 'region_failure' A whole region of servers fails
# 'prime_node_failure' A failure of the prime node that the client connnects to
# 'non_prime_node_failure' A failure of a non-prime node that the client is not connected to, but in the same region as the prime node

parser.add_argument('-e', '--experiment', type=str, choices=VALID_EXPERIMENTS, help='the experiment to plot', default='combined')
parser.add_argument('-w', '--workload', type=str, choices=VALID_WORKLOADS, help='the workload to plot', default='ycsb')
parser.add_argument('-en','--env', type=str, choices=VALID_ENVRONMENTS, help='which environmenet the experiment was run in', default='aws')
parser.add_argument('-s', '--system', type=str, choices=VALID_SYSTEMS, help='which system to plot', default='crdb')

args = parser.parse_args()

exp = args.experiment
workload = args.workload
env = args.env
sytem = args.system

if exp == 'combined':
    print("For the combined experiment, we will plot both the region failure and prime node failure experiments together for comparison.")
    fig, axes = plt.subplots(1, 2, figsize=(8, 2.2), sharex=True)


    for ax, scenario in zip(axes, ['prime_node_failure', 'region_failure']):
        raw_data_dir = f'plots/raw_data/{env}/{workload}/fault_tolerance/{sytem}/{scenario}'

        client_folders = [join(raw_data_dir, 'client', f) for f in os.listdir(join(raw_data_dir, 'client')) if '.DS_Store' not in f]
        client_csvs = [join(f, 'transactions.csv') for f in client_folders]
        client_dataframes = []

        # -- Getting the running average throughput over time for the client that experienced the failure --
        # 1. Load in the data
        failure_client_df = pd.read_csv(join(raw_data_dir, 'client/0-0/transactions.csv'))
        # 2. Convert 'received_at' from nanoseconds to datetime
        # We use unit='ns' because your timestamps are 19-digit Unix nanoseconds
        failure_client_df['received_at_dt'] = pd.to_datetime(failure_client_df['received_at'], unit='ns')
        # 3. Set the timestamp as the index and sort
        failure_client_df = failure_client_df.sort_values('received_at_dt')
        failure_client_df = failure_client_df.set_index('received_at_dt')
        # 4. Resample to calculate throughput
        # We resample to 100ms bins to keep high resolution, then count the number of txn_ids
        # Multiplying by 10 converts "transactions per 100ms" to "transactions per second" (TPS)
        resolution = '100L' # 100 Milliseconds
        failure_client_tps_series = failure_client_df['txn_id'].resample(resolution).count() * 10
        # 5. Calculate the rolling average (e.g., over 2 surrounding seconds)
        # Since our resolution is 100ms, a 2-second window is 20 periods
        failure_client_throughput_smooth = failure_client_tps_series.rolling(
            window=TPS_WINDOW_SIZE, 
            center=True, 
            min_periods=1
        ).mean()
        time_since_start = (failure_client_throughput_smooth.index - failure_client_throughput_smooth.index[0]).total_seconds()
        failure_client_throughput_smooth.index = time_since_start

        for csv in client_csvs:
            df = pd.read_csv(csv)
            client_dataframes.append(df)
        all_clients_df = pd.concat(client_dataframes, ignore_index=True)
        all_clients_df['received_at_dt'] = pd.to_datetime(all_clients_df['received_at'], unit='ns')
        all_clients_df = all_clients_df.sort_values('received_at_dt')
        all_clients_df = all_clients_df.set_index('received_at_dt')
        resolution = '100L' # 100 Milliseconds
        all_clients_tps_series = all_clients_df['txn_id'].resample(resolution).count() * 10
        all_clients_throughput_smooth = all_clients_tps_series.rolling(
            window=TPS_WINDOW_SIZE, 
            center=True, 
            min_periods=1
        ).mean()
        time_since_start = (all_clients_throughput_smooth.index - all_clients_throughput_smooth.index[0]).total_seconds()
        all_clients_throughput_smooth.index = time_since_start

        # Only generate 1 entry in the legend
        if scenario == 'region_failure':
            ax.plot(failure_client_throughput_smooth.index, failure_client_throughput_smooth.values, label='Failure Region Throughput', color='red')
            ax.plot(all_clients_throughput_smooth.index, all_clients_throughput_smooth.values, label='Total Throughput', color='blue')
            ax.vlines(x=15, ymin=0, ymax=max(all_clients_throughput_smooth)*1.1, color='brown', linestyle='--', label='Failure Start/End')
            ax.vlines(x=45, ymin=0, ymax=max(all_clients_throughput_smooth)*1.1, color='brown', linestyle='--')
        else:
            ax.plot(failure_client_throughput_smooth.index, failure_client_throughput_smooth.values, color='red')
            ax.plot(all_clients_throughput_smooth.index, all_clients_throughput_smooth.values, color='blue')
            ax.vlines(x=15, ymin=0, ymax=max(all_clients_throughput_smooth)*1.1, color='brown', linestyle='--')
            ax.vlines(x=45, ymin=0, ymax=max(all_clients_throughput_smooth)*1.1, color='brown', linestyle='--')

        if scenario == 'prime_node_failure':
            scenario = 'Single Node Failure'
        ax.set_title(scenario.replace('_', ' ').title())
        ax.set_xlim(0, 60)
        ax.set_ylim(0, max(all_clients_throughput_smooth)*1.1)
        ax.set_ylabel('Throughput (txn/s)')
        ax.set_xlabel('Time (s)')
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))
        ax.grid(True)

else:
    raw_data_dir = f'plots/raw_data/{env}/{workload}/fault_tolerance/{sytem}/{exp}'

    client_folders = [join(raw_data_dir, 'client', f) for f in os.listdir(join(raw_data_dir, 'client')) if '.DS_Store' not in f]
    client_csvs = [join(f, 'transactions.csv') for f in client_folders]
    client_dataframes = []

    # -- Getting the running average throughput over time for the client that experienced the failure --
    # 1. Load in the data
    failure_client_df = pd.read_csv(join(raw_data_dir, 'client/0-0/transactions.csv'))
    # 2. Convert 'received_at' from nanoseconds to datetime
    # We use unit='ns' because your timestamps are 19-digit Unix nanoseconds
    failure_client_df['received_at_dt'] = pd.to_datetime(failure_client_df['received_at'], unit='ns')
    # 3. Set the timestamp as the index and sort
    failure_client_df = failure_client_df.sort_values('received_at_dt')
    failure_client_df = failure_client_df.set_index('received_at_dt')
    # 4. Resample to calculate throughput
    # We resample to 100ms bins to keep high resolution, then count the number of txn_ids
    # Multiplying by 10 converts "transactions per 100ms" to "transactions per second" (TPS)
    resolution = '100L' # 100 Milliseconds
    failure_client_tps_series = failure_client_df['txn_id'].resample(resolution).count() * 10
    # 5. Calculate the rolling average (e.g., over 2 surrounding seconds)
    # Since our resolution is 100ms, a 2-second window is 20 periods
    failure_client_throughput_smooth = failure_client_tps_series.rolling(
        window=TPS_WINDOW_SIZE, 
        center=True, 
        min_periods=1
    ).mean()
    time_since_start = (failure_client_throughput_smooth.index - failure_client_throughput_smooth.index[0]).total_seconds()
    failure_client_throughput_smooth.index = time_since_start

    # -- Getting the running average throughput over time for all clients --
    # 1. Load in the data
    for csv in client_csvs:
        df = pd.read_csv(csv)
        client_dataframes.append(df)
    all_clients_df = pd.concat(client_dataframes, ignore_index=True)
    # 2. Convert 'received_at' from nanoseconds to datetime
    all_clients_df['received_at_dt'] = pd.to_datetime(all_clients_df['received_at'], unit='ns')
    # 3. Set the timestamp as the index and sort
    all_clients_df = all_clients_df.sort_values('received_at_dt')
    all_clients_df = all_clients_df.set_index('received_at_dt')
    # 4. Resample to calculate throughput
    resolution = '100L' # 100 Milliseconds
    all_clients_tps_series = all_clients_df['txn_id'].resample(resolution).count() * 10
    # 5. Calculate the rolling average (e.g., over 2 surrounding seconds)
    all_clients_throughput_smooth = all_clients_tps_series.rolling(
        window=TPS_WINDOW_SIZE, 
        center=True, 
        min_periods=1
    ).mean()
    time_since_start = (all_clients_throughput_smooth.index - all_clients_throughput_smooth.index[0]).total_seconds()
    all_clients_throughput_smooth.index = time_since_start

    # -- Plotting the results --
    # Set up figure
    plt.rcParams.update({'font.size': 12})
    #matplotlib.use('TkAgg')
    fig = plt.figure(figsize=(8, 4))

    plt.plot(failure_client_throughput_smooth.index, failure_client_throughput_smooth.values, label='Failure Region Throughput', color='red')
    plt.plot(all_clients_throughput_smooth.index, all_clients_throughput_smooth.values, label='Total Throughput', color='blue')
    plt.vlines(x=15, ymin=0, ymax=max(all_clients_throughput_smooth)*1.1, color='brown', linestyle='--', label='Failure Start/End')
    plt.vlines(x=45, ymin=0, ymax=max(all_clients_throughput_smooth)*1.1, color='brown', linestyle='--')

    plt.xlim(0, 60)
    plt.ylim(0, max(all_clients_throughput_smooth)*1.1)

    plt.ylabel('Throughput (txn/s)')
    plt.xlabel('Time (s)')
    plt.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))
    plt.grid(True)

fig.legend(loc='upper center', bbox_to_anchor=(0.5, 1.1), ncol=3)
plt.tight_layout()

# Save figure
output_path = f'plots/output/{env}/{workload}/fault_tolerance_{workload}_{exp}'
png_path = output_path + '.png'
pdf_path = output_path + '.pdf'
os.makedirs('/'.join(output_path.split('/')[:-1]), exist_ok=True)
plt.savefig(png_path, dpi=300, bbox_inches='tight')
plt.savefig(pdf_path, bbox_inches='tight')
plt.show()

print("Done")

# I want to plot a trace of a database's throughput over time 60s. The experiment shows a failure (happens after ~15s) and the failed noder recovers after another ~30s. This is how 