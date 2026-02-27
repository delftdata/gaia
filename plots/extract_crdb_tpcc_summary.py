import os, time
from os.path import join, isdir
import pandas as pd
import argparse
from datetime import datetime, timezone

SCENARIO = 'vary_hw' # 'packet_loss', 'network', 'server_skew', 'vary_hw', 'baseline', 'skew', 'scalability'

raw_data_dir = f'plots/raw_data/aws/tpcc/{SCENARIO}/crdb'

x_vals = [d for d in os.listdir(raw_data_dir) if isdir(join(raw_data_dir, d))]

df_cols = ['x_val', 'throughput', 'p50_latency', 'p95_latency', 'p99_latency']
data = pd.DataFrame(columns=df_cols)

for x in x_vals:
    if SCENARIO == 'server_skew' or SCENARIO == 'vary_hw':
        cur_col = [x, 0, 0, 0, 0]
    else:
        cur_col = [float(x), 0, 0, 0, 0]
    
    log_files = [f for f in os.listdir(join(raw_data_dir, x, 'raw_logs')) if 'benchmark_container' in f]

    for log in log_files:
        with open(join(raw_data_dir, x, 'raw_logs', log), 'r') as f:
            log_lines = f.readlines()
            for i in range(len(log_lines)):
                line = log_lines[i]
                if '_elapsed_______tpmC____efc__avg(ms)__p50(ms)__p90(ms)__p95(ms)__p99(ms)_pMax(ms)' in line:
                    # The next line contains the data we need
                    data_line = log_lines[i+1]
                    data_parts = data_line.split(' ')
                    data_parts = [part for part in data_parts if part] # Remove empty parts caused
                    cur_col[1] += int(float(data_parts[1])) # tpmC is the throughput
                    cur_col[2] += float(data_parts[4]) # p50 latency
                    cur_col[3] += float(data_parts[6]) # p95 latency
                    cur_col[4] += float(data_parts[7]) # p99 latency

    cur_col = [cur_col[0], cur_col[1], cur_col[2]/len(log_files), cur_col[3]/len(log_files), cur_col[4]/len(log_files)]
    data.loc[len(data)] = cur_col

data = data.sort_values('x_val')

print("Final data:")
print(data)

print("Done")
