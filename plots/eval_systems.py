import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
import matplotlib.ticker as ticker
import pandas as pd
import numpy as np
import os
import argparse

VALID_SCENARIOS = ['baseline', 'skew', 'scalability', 'network', 'packet_loss', 'sunflower']
VALID_WORKLOADS = ['ycsb', 'tpcc', 'movr', 'movie', 'pps', 'dsh', 'smallbank']
VALID_ENVIRONMENTS = ['local', 'st', 'aws']
DEFAULT_LAT_PERCENTILES = "50;95;99" # Extracted data will contain p50, p90, p95, p99. For the plots we will use p50, p99
TXN_TYPES = ['lsh', 'fsh', 'mh']
WORKLOAD_CAPITALIZATION = {'ycsb': 'YCSB', 'tpcc': 'TPC-C', 'movr': 'MovR', 'movie': 'DS Movie', 'pps': 'PPS', 'dsh': 'DS Hotels', 'smallbank': 'SmallBank'}
BAR_WIDTH = 0.18

def darken_color(color, factor):
    """Darkens a color toward black. Factor ∈ [0, 1], where 1 = original color, 0 = black."""
    rgb = mcolors.to_rgb(color)
    return tuple(c * factor for c in rgb)

def lighten_color(color, factor):
    """Lightens a color toward white. Factor ∈ [0, 1], where 1 = original color, 0 = white."""
    rgb = mcolors.to_rgb(color)
    return tuple(1 - (1 - c) * factor for c in rgb)

def make_plot(plot='baseline', workload='ycsb', env='st', latency_percentiles=[50, 95, 99], skip_aborts=False, separate_latencies=False, log_latencies=True, costs_per_txn=True):

    if workload == "pps":
        if plot == 'baseline':
            x_lab = 'OrderProduct Multi-Home (%)'
        elif plot == 'skew':
            x_lab = 'Skew Factor (HOT)'
        elif plot == 'scalability':
            x_lab = 'Input Throughput (txn/s)'
        elif plot == 'network':
            x_lab = 'Extra delay (ms)'
        elif plot == 'packet_loss':
            x_lab = 'Packets lost (%)'
        elif plot == 'example':
            x_lab = 'Example x-axis'
    else:
        if plot == 'baseline':
            x_lab = 'Geo-distribution (%)'
        elif plot == 'skew':
            x_lab = 'Skew factor (Theta)'
        elif plot == 'scalability':
            x_lab = 'Input Throughput (txn/s)'
        elif plot == 'network':
            x_lab = 'Extra delay (ms)'
        elif plot == 'packet_loss':
            x_lab = 'Packets lost (%)'
        elif plot == 'sunflower':
            x_lab = 'Sunflower falloff'
        elif plot == 'example':
            x_lab = 'Example x-axis'

    # Read data from CSV
    csv_path = f'plots/data/{env}/{workload}/{plot}.csv'
    data = pd.read_csv(csv_path)

    # Extract data
    xaxis_points = data['x_var']
    # For some experiments, we have to adjust the x_values
    if workload == 'tpcc' and plot == 'baseline':
        xaxis_points = [0, 4, 8, 15, 20, 25, 29, 32, 34, 36, 38, 39]
        if len(list(set(data['x_var']))) == 17: # Extended version of TPC-C with up to 88% FSH & MH
            #               0.00;0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.25;0.30;0.40;0.50;0.60;0.70;0.80;0.90;1.00]
            xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,52.4,56.0,61.4,66.1,70.4,74.6,79.1,83.6,88.0]
        elif len(list(set(data['x_var']))) == 16: # Detock and SLOG sometimes have no datapoint for 0% FSH & MH
            #               0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.25;0.30;0.40;0.50;0.60;0.70;0.80;0.90;1.00]
            xaxis_points = [4.66,8.96,19.9,27.1, 33.0,42.0,48.0,52.4,56.0,61.4,66.1,70.4,74.6,79.1,83.6,88.0]
        elif len(list(set(data['x_var']))) == 13: # For CRDB we run less x-axis points
            #               0.00;0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.30;0.50;0.60;0.80;1.00]
            xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,56.0,66.1,74.6,79.1,88.0]
        crdb_baseline_tpcc_xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,56.0,66.1,74.6,79.1,88.0]
        data['x_axis_points'] = xaxis_points
        xaxis_points = data['x_axis_points']
    if workload == 'smallbank' and plot == 'baseline':
        xaxis_points = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 49.15]
    #elif workload == 'tpcc' and plot == 'skew':
    #    xaxis_points = [250 - point for point in xaxis_points]
    elif workload == 'movr' and plot == 'baseline':
        xaxis_points = [x * 0.35 for x in xaxis_points]
    elif workload == 'dsh' and plot == 'baseline':
        xaxis_points = [x * 100 for x in xaxis_points]

    if not skip_aborts:
        metrics = ['throughput', 'latency', 'aborts', 'bytes', 'cost']
        y_labels = [
            'Throughput (txn/s)',
            'Latency (ms)',
            'Aborts (%)',
            'Data transfers (GB/s)',
            'Hourly Cost ($/h)'
        ]
        y_labels_crdb = [
            'Throughput CRDB',
            'Latency CRDB',
            'Aborts CRDB',
            'Data transfers CRDB',
            'Hourly Cost CRDB'
        ]
        if separate_latencies:
            subplot_titles = ['Throughput', 'Latency (by txn type)', 'Aborts', 'Data transfers', 'Cost']
        else:
            subplot_titles = ['Throughput', 'Latency (log scale)', 'Aborts', 'Data transfers', 'Cost']
    else:
        metrics = ['throughput', 'latency', 'bytes', 'cost']
        y_labels = [
            'Throughput\n(txn/s)',
            'Latency (ms)',
            'Data transfers\n(GB/s)',
            'Hourly Cost ($/h)'
        ]
        y_labels_crdb = [
            'Throughput\nCRDB',
            'Latency\nCRDB',
            'Data transfers\nCRDB',
            'Hourly Cost CRDB'
        ]
        if separate_latencies:
            subplot_titles = ['Throughput', 'Latency (by txn type)', 'Data transfers', 'Cost']
        else:
            subplot_titles = ['Throughput', 'Latency (log scale)', 'Data transfers', 'Cost']
    
    if costs_per_txn:
        subplot_titles[-1] = 'Cost per 10k txns'
        y_labels[-1] = 'Cost per\n10k txns (¢)'
        y_labels_crdb[-1] = 'Cost per\n10k txns CRDB'
    if workload == 'tpcc':
        subplot_titles = ['' for title in subplot_titles] # We don't want to duplicate and clutter the plot

    databases = ['Calvin', 'SLOG', 'Detock', 'Janus', 'CockroachDB']
    line_styles = ['-', '--', '-.', ':', (1, (1,1)), (0, (3, 1, 1, 1, 1, 1))]
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:brown']

    # Configure Matplotlib global font size
    fs = 8
    plt.rcParams.update({
        'font.size': 9,        # Increase font size for better readability
        'axes.titlesize': 10,
        'axes.labelsize': 9,
        'xtick.labelsize': fs,
        'ytick.labelsize': fs,
        'legend.fontsize': 9
    })

    # Create figure and subplots
    if env == 'aws':
        fig, axes = plt.subplots(1, len(metrics), figsize=(15, 2), sharex=True)
    else:
        fig, axes = plt.subplots(1, len(metrics), figsize=(15, 2.5), sharex=True)

    for ax, metric, y_label, subplot_title, crdb_ylabel in zip(axes, metrics, y_labels, subplot_titles, y_labels_crdb):
        # 1. Create the twin axis for this specific subplot
        if metric != 'latency':
            ax_twin = ax.twinx()
            #ax_twin.set_ylabel(f'CRDB {y_label.split()[-1]}', color='tab:brown')
            ax_twin.tick_params(axis='y')
        min_latency = 1_000_000_000
        for db, color, style in zip(databases, colors, line_styles):
            # Determine which axis to use
            current_ax = ax_twin if db == 'CockroachDB' else ax
            if plot == 'scalability':
                column_name = f'{db}_input_throughput'
                if column_name.lower() in data.columns:
                    #xaxis_points = data[data[column_name.lower()].notnull()][column_name.lower()]
                    xaxis_points = data[column_name.lower()]
            if metric != 'latency':
                column_name = f'{db}_{metric}'
                if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                    if metric == 'bytes':
                        data[column_name.lower()] = data[column_name.lower()] / 1_000_000_000
                    current_ax.plot(xaxis_points[data[column_name.lower()].notnull()], data[data[column_name.lower()].notnull()][column_name.lower()], label=db, color=color, linestyle=style)
                    # This is just a hack to keep CRDB in the legend
                    if db == 'CockroachDB':
                        ax.plot([-1], [-1],label=db, color=color, linestyle=style)
            else:
                cur_colors = [lighten_color(color=color, factor=0.5), mcolors.to_rgb(color), darken_color(color=color, factor=0.5)]
                if separate_latencies:
                    fixed_percentile = '95'
                    for txn_type, cur_color in zip(TXN_TYPES, cur_colors):
                        if db.lower() == 'calvin' or db.lower() == 'janus':
                            cur_color = cur_colors[1] # Janus & Calvin do not differentiate between txn types
                        column_name = f'{db}_{txn_type}_p{fixed_percentile}'
                        if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                            ax.plot(xaxis_points[data[column_name.lower()].notnull()], data[data[column_name.lower()].notnull()][column_name.lower()], label=db, color=cur_color, linestyle=style)
                            min_latency = min(min_latency, min(data[column_name.lower()]))
                else:
                    for percentile, cur_color in zip(latency_percentiles, cur_colors):
                        column_name = f'{db}_p{percentile}'
                        if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                            ax.plot(xaxis_points[data[column_name.lower()].notnull()], data[data[column_name.lower()].notnull()][column_name.lower()], label=db, color=cur_color, linestyle=style)
                            min_latency = min(min_latency, min(data[column_name.lower()]))
                if log_latencies:
                    ax.set_yscale('log')
                    
        ax.set_title(subplot_title)
        if env != 'aws' or workload != 'ycsb':
            ax.set_xlabel(x_lab)
        ax.set_ylabel(y_label)
        ax.grid(True)
        if metric != 'latency':
            ax_twin.set_ylim(bottom=0)
            ax_twin.set_ylabel(crdb_ylabel)
        if workload == 'ycsb':
            if plot == 'baseline':
                ax.set_xticks(np.linspace(0, 100, 6))  # 0%, 20%, ..., 100%
                ax.set_xlim(0, 100)
                ax.minorticks_off()
                if metric == 'throughput':
                    ax_twin.set_ylim(0, 10000)
            elif plot == 'skew':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
            elif plot == 'scalability':
                if env == 'aws':
                    ax.set_xlim(left=0, right=200_000)
                    ax.minorticks_off()
                    if metric == 'throughput':
                        ax.set_ylim(top=50_000)
                        ax_twin.set_ylim(0, 15000)
                    elif metric == 'latency':
                        ax.set_ylim(top=100000)
                    elif metric == 'bytes':
                        ax.set_ylim(top=3)
                else: # For the ST cluster experiments
                    ax.set_xlim(left=0, right=50_000)
                    ax.minorticks_off()
                    if metric == 'throughput':
                        ax.set_ylim(top=20_000)
                    elif metric == 'latency':
                        ax.set_ylim(top=100_000)
                    elif metric == 'bytes':
                        ax.set_ylim(top=0.25)
            elif plot == 'network':
                ax.set_xlim(left=0, right=1000)
                if metric == 'throughput':
                    ax_twin.set_ylim(0, 10000)
            elif plot == 'packet_loss':
                ax.set_xlim(0, 10)
                if metric == 'throughput':
                    ax_twin.set_ylim(0, 10000)
            elif plot == 'sunflower':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
        elif workload == 'tpcc':
            if plot == 'baseline':
                ax.set_xticks(np.linspace(0, 100, 6))  # 0%, 20%, ..., 100%
                ax.set_xlim(0, 100)
                ax.minorticks_off()
                if metric == 'throughput':
                    ax_twin.set_ylim(0, 1200)
            elif plot == 'skew':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
            elif plot == 'scalability':
                ax.set_xlim(left=0, right=60_000)
                if metric == 'throughput':
                    ax.set_ylim(top=40_000)
                    ax_twin.set_ylim(0, 900)
                elif metric == 'bytes':
                    if env == 'st':
                        ax.set_ylim(top=0.2)
                ax.minorticks_off()
            elif plot == 'network':
                ax.set_xlim(left=0, right=1000)
                if metric == 'throughput':
                    ax_twin.set_ylim(0, 1200)
            elif plot == 'packet_loss':
                ax.set_xlim(0, 10)
                if metric == 'throughput':
                    ax_twin.set_ylim(0, 1200)
            elif plot == 'sunflower':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
        elif workload == 'pps':
            if plot == 'baseline':
                ax.set_xticks(np.linspace(0, 100, 6))  # 0%, 20%, ..., 100%
                ax.set_xlim(0, 100)
            elif plot == 'skew':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
                ax.set_xscale('log')
            elif plot == 'scalability':
                ax.set_xlim(left=0, right=150_000)
            elif plot == 'network':
                ax.set_xlim(left=0, right=1000)
            elif plot == 'packet_loss':
                ax.set_xlim(0, 10)
        elif workload == 'smallbank':
            if plot == 'baseline':
                ax.set_xticks(np.linspace(0, 100, 6))  # 0%, 20%, ..., 100%
                ax.set_xlim(0, 100)
            elif plot == 'skew':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
                ax.set_xscale('log')
            elif plot == 'scalability':
                ax.set_xlim(left=0, right=100_000)
            elif plot == 'network':
                ax.set_xlim(left=0, right=1000)
            elif plot == 'packet_loss':
                ax.set_xlim(0, 10)
        elif workload == 'movie':
            if plot == 'baseline':
                ax.set_xticks(np.linspace(0, 100, 6))  # 0%, 20%, ..., 100%
                ax.set_xlim(0, 100)
            elif plot == 'skew':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
                ax.set_xscale('log')
            elif plot == 'scalability':
                ax.set_xlim(left=0, right=150_000)
                if metric == 'throughput':
                    ax.set_ylim(top=60_000)
                elif metric == 'latency':
                    ax.set_ylim(top=100_000)
                elif metric == 'bytes':
                    ax.set_ylim(top=0.25)
            elif plot == 'network':
                ax.set_xlim(left=0, right=1000)
            elif plot == 'packet_loss':
                ax.set_xlim(0, 10)
        elif workload == 'dsh':
            if plot == 'baseline':
                ax.set_xticks(np.linspace(0, 100, 6))  # 0%, 20%, ..., 100%
                ax.set_xlim(0, 100)
            elif plot == 'skew':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
            elif plot == 'scalability':
                ax.set_xlim(left=0, right=100_000)
            elif plot == 'network':
                ax.set_xlim(left=0, right=1000)
            elif plot == 'packet_loss':
                ax.set_xlim(0, 10)
            elif plot == 'sunflower':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
        else:
            if plot == 'baseline':
                if workload == 'movr':
                    ax.set_xticks(np.linspace(0, 35, 6))  # 0%, 7.5%, ..., 35%
                    ax.set_xlim(0, 35)
                else:
                    ax.set_xticks(np.linspace(0, 100, 6))  # 0%, 20%, ..., 100%
                    ax.set_xlim(0, 100)
            elif plot == 'skew':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
            elif plot == 'scalability':
                ax.set_xlim(left=0, right=50_000)
            elif plot == 'network':
                ax.set_xlim(left=0, right=1000)
            elif plot == 'packet_loss':
                ax.set_xlim(0, 10)
            elif plot == 'sunflower':
                ax.set_xticks(np.linspace(0.0, 1.0, 6))  # 0.0, 0.2, ..., 1.0
                ax.set_xlim(0, 1)
        if not log_latencies or metric != 'latency':
            ax.set_ylim(bottom=0)  # Remove extra whitespace below y=0
        else:
            if env == 'st':
                ax.set_ylim(bottom=1)
            else:
                ax.set_ylim(bottom=1)
        if metric == 'cost' and plot == 'scalability':
            ax.set_ylim(0,10)
            ax_twin.set_ylim(0,50)
            if workload == 'ycsb':
                ax.set_ylim(0,5)
                ax_twin.set_ylim(0,10)
        elif metric == 'throughput':
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))
            if workload == 'ycsb':
                ax_twin.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))
        if plot == 'scalability':
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))

    # Add legend and adjust layout
    handles, labels = axes[-1].get_legend_handles_labels()
    labels = [l[:1].capitalize()+l[1:] for l in labels]
    if workload != 'tpcc' or env != 'aws':
        fig.legend(handles, labels, loc='upper center', ncol=len(databases), bbox_to_anchor=(0.5, 1.1))
    workload_type = 'default'
    if plot == 'skew':
        workload_type = 'skew'
    elif plot == 'baseline':
        workload_type = 'access\npatterns'
    elif plot == 'sunflower':
        workload_type = 'sunflower'
    fig.text(
        0.02, 0.5,                # (x, y) in figure coordinates — x=0.02 pushes it to the left
        f'{WORKLOAD_CAPITALIZATION[workload]} ({workload_type})',        # the label text
        va='center', ha='center', # center vertically
        rotation='vertical',      # vertical orientation
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout(rect=[0.03, 0, 1, 1])  # Further reduce whitespace

    # Save figures
    output_path = f'plots/output/{env}/{workload}/{plot}_{workload}'
    png_path = output_path + '.png'
    pdf_path = output_path + '.pdf'
    os.makedirs('/'.join(output_path.split('/')[:-1]), exist_ok=True)
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.show()

def make_bar_plot(plot='vary_hw', workload='ycsb', env='st', latency_percentiles=[50, 99], skip_aborts=True, separate_latencies=False, log_latencies=True, costs_per_txn=True):

    if plot == 'vary_hw':
        x_lab = 'VM Type'
    elif plot == 'server_skew':
        x_lab = 'Server Distribution'

    # Read data from CSV
    csv_path = f'plots/data/{env}/{workload}/{plot}.csv'
    data = pd.read_csv(csv_path)

    # Extract data
    xaxis_points = data['x_var']

    if not skip_aborts:
        metrics = ['throughput', 'latency', 'aborts', 'bytes', 'cost']
        y_labels = [
            'Throughput\n(txn/s)',
            'Latency (ms)',
            'Aborts (%)',
            'Data transfers\n(GB/s)',
            'Hourly Cost ($/h)'
        ]
        y_labels_crdb = [
            'Throughput\nCRDB',
            'Latency\nCRDB',
            'Aborts\nCRDB',
            'Data transfers\nCRDB',
            'Hourly Cost CRDB'
        ]
        subplot_titles = ['Throughput', 'Latency (log scale)', 'Aborts', 'Data transfers', 'Cost']
    else:
        metrics = ['throughput', 'latency', 'bytes', 'cost']
        y_labels = [
            'Throughput\n(txn/s)',
            'Latency (ms)',
            'Data transfers\n(GB/s)',
            'Hourly Cost ($/h)'
        ]
        y_labels_crdb = [
            'Throughput\nCRDB',
            'Latency\nCRDB',
            'Data transfers\nCRDB',
            'Hourly Cost CRDB'
        ]
        subplot_titles = ['Throughput', 'Latency (log scale)', 'Data transfers', 'Cost']

    if costs_per_txn:
        subplot_titles[-1] = 'Cost per 10k txns'
        y_labels[-1] = 'Cost per\n10k txns (¢)'
        y_labels_crdb[-1] = 'Cost per\n10k txns CRDB'
    if workload == 'tpcc' and env == 'aws':
        subplot_titles = ['' for title in subplot_titles] # We don't want to duplicate and clutter the plot

    databases = ['Calvin', 'SLOG', 'Detock', 'Janus', 'CockroachDB']
    line_styles = ['-', '--', '-.', ':', '-..']
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:brown']

    # Configure Matplotlib global font size
    fs = 8
    plt.rcParams.update({
        'font.size': 9,        # Increase font size for better readability
        'axes.titlesize': 10,
        'axes.labelsize': 9,
        'xtick.labelsize': fs,
        'ytick.labelsize': fs,
        'legend.fontsize': 9
    })

    # Create figure and subplots
    if env == 'aws':
        # Make the latency subplot wider to accomodate for the side by side bars
        if len(metrics) == 5:
            wr = [1, 1.5, 1, 1, 1]
        elif len(metrics) == 4:
            wr = [1, 1.5, 1, 1]
        fig, axes = plt.subplots(1, len(metrics), width_ratios=wr, figsize=(15, 1.75), sharex=True)
    else:
        fig, axes = plt.subplots(1, len(metrics), figsize=(15, 2.3), sharex=True)

    default_xaxis_points = [-2*BAR_WIDTH + x for x in range(len(xaxis_points))]
    for ax, metric, y_label, subplot_title, crdb_ylabel in zip(axes, metrics, y_labels, subplot_titles, y_labels_crdb):
        # 1. Create the twin axis for this specific subplot
        if metric != 'latency':
            ax_twin = ax.twinx()
            #ax_twin.set_ylabel(f'CRDB {y_label.split()[-1]}', color='tab:brown')
            ax_twin.tick_params(axis='y')
        min_latency = 1_000_000_000 # Small hack to get a 100% overboard value
        for db, color, style, i in zip(databases, colors, line_styles, range(len(databases))):
            # Determine which axis to use
            current_ax = ax_twin if db == 'CockroachDB' else ax
            cur_x_axis_points = [x+i*BAR_WIDTH for x in default_xaxis_points]
            if metric != 'latency' and metric != 'cost':
                column_name = f'{db}_{metric}'
                if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                    if metric == 'bytes':
                        data[column_name.lower()] = data[column_name.lower()] / 1_000_000_000
                    current_ax.bar(cur_x_axis_points, data[column_name.lower()], width=BAR_WIDTH, label=db, color=color, edgecolor='#000000')
            elif metric == 'cost':
                cur_colors = [mcolors.to_rgb(color), lighten_color(color=color, factor=0.5)]
                column_name = f'{db}_fixed_cost'
                if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                    # This is just a hack to keep CRDB in the legend
                    if db == 'CockroachDB':
                        ax.bar(cur_x_axis_points[0], [0], width=BAR_WIDTH, label=db, color=color, edgecolor='#000000')
                    current_ax.bar(cur_x_axis_points, data[column_name.lower()], width=BAR_WIDTH, label=db, color=cur_colors[0], edgecolor='#000000')
                    min_latency = min(min_latency, min(data[column_name.lower()]))
                    next_column_name = f'{db}_cost'
                    current_ax.bar(cur_x_axis_points, data[next_column_name.lower()]-data[column_name.lower()], bottom=data[column_name.lower()], width=BAR_WIDTH, color=cur_colors[1], edgecolor='#000000')
                pass
            else:
                cur_colors = [mcolors.to_rgb(color), lighten_color(color=color, factor=0.5)]
                if separate_latencies:
                    fixed_percentile = '95'
                    for txn_type, cur_color in zip(TXN_TYPES, cur_colors):
                        if db.lower() == 'calvin' or db.lower() == 'janus':
                            cur_color = cur_colors[1] # Janus & Calvin do not differentiate between txn types
                        column_name = f'{db}_{txn_type}_p{fixed_percentile}'
                        if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                            ax.bar(cur_x_axis_points, data[column_name.lower()], width=BAR_WIDTH, label=db, color=cur_color, edgecolor='#000000')
                            min_latency = min(min_latency, min(data[column_name.lower()]))
                else:
                    # For bar plot we only want 2 side-by-side bars anyway, so we just hardcode this
                    column_name = f'{db}_p{latency_percentiles[0]}'
                    stacked_side_by_side_cur_p50_x_points = [x-BAR_WIDTH/2 for x in cur_x_axis_points]
                    if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                        ax.bar(stacked_side_by_side_cur_p50_x_points, data[column_name.lower()], width=BAR_WIDTH/2, label=db, color=cur_colors[0], edgecolor='#000000')
                        min_latency = min(min_latency, min(data[column_name.lower()]))
                        next_column_name = f'{db}_p{latency_percentiles[1]}'
                        ax.bar(cur_x_axis_points, data[next_column_name.lower()], width=BAR_WIDTH/2, color=cur_colors[1], edgecolor='#000000')
                if log_latencies and metric == 'latency':
                    ax.set_yscale('log')
                    
        ax.set_title(subplot_title)
        if env != 'aws' or workload != 'ycsb':
            ax.set_xlabel(x_lab)
        ax.set_ylabel(y_label)
        x = np.arange(len(xaxis_points))
        if metric != 'latency':
            ax_twin.set_ylim(bottom=0)
            ax_twin.set_ylabel(crdb_ylabel)
            if metric == 'throughput':
                if plot == 'baseline':
                    ax_twin.set_ylim(0, 500)
                elif plot == 'vary_hw':
                    if workload == 'ycsb':
                        ax_twin.set_ylim(0, 14000)
                    elif workload == 'tpcc':
                        ax_twin.set_ylim(0, 800)
                elif plot == 'server_skew':
                    if workload == 'ycsb':
                        ax_twin.set_ylim(0, 7500)
                    elif workload == 'tpcc':
                        ax_twin.set_ylim(0, 800)
        if plot == 'vary_hw':
            xaxis_points_final = [x[:-5] for x in xaxis_points]
        elif plot == 'server_skew':
            sever_skew_mappings = {'balanced': 'unif.',
                                   'us-west+': 'usw+',
                                   'us-west+_eu-west+': 'usw+\neu+',
                                   'us-west++': 'usw++',
                                   'us-west++_eu-west++': 'usw++\neu++',
                                   'us-west_only': 'usw only'}
            xaxis_points_final = [sever_skew_mappings[x] for x in xaxis_points]
        ax.set_xticks(x, xaxis_points_final, fontsize=fs)
        ax.grid(which='major', axis='y')
        
        if not log_latencies or metric != 'latency':
            ax.set_ylim(bottom=0)  # Remove extra whitespace below y=0
        else:
            ax.set_ylim(bottom=1)
        if metric == 'throughput':
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))
            if workload == 'ycsb':
                ax_twin.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))

    # Add legend and adjust layout
    handles, labels = axes[-1].get_legend_handles_labels()
    labels = [l[:1].capitalize()+l[1:] for l in labels]
    if workload != 'tpcc':
        fig.legend(handles, labels, loc='upper center', ncol=len(databases), bbox_to_anchor=(0.5, 1.1))
    workload_type = 'default'
    if plot == 'skew':
        workload_type = 'skew'
    elif plot == 'baseline':
        workload_type = 'access\npatterns'
    fig.text(
        0.02, 0.5,                # (x, y) in figure coordinates — x=0.02 pushes it to the left
        f'{WORKLOAD_CAPITALIZATION[workload]}\n({workload_type})',        # the label text
        va='center', ha='center', # center vertically
        rotation='vertical',      # vertical orientation
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout(rect=[0.03, 0, 1, 1])  # Further reduce whitespace

    # Save figures
    output_path = f'plots/output/{env}/{workload}/{plot}_{workload}'
    png_path = output_path + '.png'
    pdf_path = output_path + '.pdf'
    os.makedirs('/'.join(output_path.split('/')[:-1]), exist_ok=True)
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.show()

def make_resource_util_plots(plot='baseline', workload='ycsb', env='st'):
    
    # Read data from CSV
    csv_path = f'plots/data/{env}/{workload}/{plot}_resource_util.csv'
    data = pd.read_csv(csv_path)

    if plot == 'baseline':
        x_lab = 'Geo-distribution (%)'
        x_lim = (0,100)
    elif plot == 'skew':
        x_lab = 'Skew factor (Theta)'
        x_lim = (0,1)
    elif plot == 'scalability':
        x_lab = 'Input Throughput (txn/s)'
        if workload == 'ycsb':
            if env == 'aws':
                x_lim = (0,200_000)
            else:
                x_lim = (0,50_000)
        elif workload == 'tpcc':
            x_lim = (0,50_000)
        elif workload == 'pps':
            x_lim = (0,150_000)
        elif workload == 'movie':
            x_lim = (0,150_000)
        elif workload == 'smallbank':
            x_lim = (0,100_000)
        elif workload == 'movr':
            x_lim = (0,35_000)
        elif workload == 'dsh':
            x_lim = (0,100_000)
    elif plot == 'network':
        x_lab = 'Extra delay (ms)'
        x_lim = (0,1000)
    elif plot == 'packet_loss':
        x_lab = 'Packets lost (%)'
        x_lim = (0,10)
    elif plot == 'sunflower':
        x_lab = 'Sunflower falloff'
    elif plot == 'example':
        x_lab = 'Example x-axis'

    # Extract data
    xaxis_points = data['x_var']
    if workload == 'tpcc' and plot == 'baseline':
        xaxis_points = [0, 4, 8, 15, 20, 25, 29, 32, 34, 36, 38, 39]
        if len(list(set(data['x_var']))) == 17: # Extended version of TPC-C with up to 88% FSH & MH
            #               0.00;0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.25;0.30;0.40;0.50;0.60;0.70;0.80;0.90;1.00]
            xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,52.4,56.0,61.4,66.1,70.4,74.6,79.1,83.6,88.0]
        elif len(list(set(data['x_var']))) == 16: # Detock and SLOG sometimes have no datapoint for 0% FSH & MH
            #               0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.25;0.30;0.40;0.50;0.60;0.70;0.80;0.90;1.00]
            xaxis_points = [4.66,8.96,19.9,27.1, 33.0,42.0,48.0,52.4,56.0,61.4,66.1,70.4,74.6,79.1,83.6,88.0]
        elif len(list(set(data['x_var']))) == 13: # For CRDB we run less x-axis points
            #               0.00;0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.30;0.50;0.60;0.80;1.00]
            xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,56.0,66.1,74.6,79.1,88.0]
        crdb_baseline_tpcc_xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,56.0,66.1,74.6,79.1,88.0]
        data['x_axis_points'] = xaxis_points
        xaxis_points = data['x_axis_points']
    elif workload == 'dsh' and plot == 'baseline':
        xaxis_points = [x * 100 for x in xaxis_points]

    databases = ['Calvin', 'SLOG', 'Detock', 'Janus', 'CockroachDB']
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:brown']
    metrics = ['cpu_usage_percent', 'mem_usage_percent', 'net_usage_percent', 'disk_usage_percent', 'aborts']
    subplot_titles = ['CPU Util', 'Memory Util', 'Network Util', 'Disk Util', 'Aborts']
    y_labels = [
        'CPU Utilization (%)',
        'Memory Utilization (%)',
        'Network Utilization (%)',
        'Disk Utilization (%)',
        'Aborts (%)'
    ]

    # Create figure and subplots
    fig, axes = plt.subplots(1, len(metrics), figsize=(15, 2.5), sharex=True)

    for ax, metric, y_label, subplot_title in zip(axes, metrics, y_labels, subplot_titles):
        for db, color in zip(databases, colors):
            if plot == 'scalability':
                column_name = f'{db}_input_throughput'
                if column_name.lower() in data.columns:
                    #xaxis_points = data[data[column_name.lower()].notnull()][column_name.lower()]
                    xaxis_points = data[column_name.lower()]
            column_name = f'{db}_{metric}'
            if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                ax.plot(xaxis_points[data[column_name.lower()].notnull()], data[data[column_name.lower()].notnull()][column_name.lower()], label=db, color=color)
        ax.set_title(subplot_title)
        ax.set_ylabel(y_label)
        ax.set_xlabel(x_lab)
        ax.set_ylim(0, 100)
        ax.set_xlim(x_lim)
        ax.grid(True)

    if plot == 'scalability':
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))

    # Add legend and adjust layout
    handles, labels = axes[-1].get_legend_handles_labels()
    labels = [l[:1].capitalize()+l[1:] for l in labels]
    fig.legend(handles, labels, loc='upper center', ncol=len(databases), bbox_to_anchor=(0.5, 1.1))
    fig.text(
        0.02, 0.5,                # (x, y) in figure coordinates — x=0.02 pushes it to the left
        f'{WORKLOAD_CAPITALIZATION[workload]} Resource\nUtilization',        # the label text
        va='center', ha='center', # center vertically
        rotation='vertical',      # vertical orientation
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout(rect=[0.03, 0, 1, 1])  # Further reduce whitespace

    # Save figures
    output_path = f'plots/output/{env}/{workload}/{plot}_{workload}_resource_util'
    png_path = output_path + '.png'
    pdf_path = output_path + '.pdf'
    os.makedirs('/'.join(output_path.split('/')[:-1]), exist_ok=True)
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.show()

def make_resource_util_bar_plots(plot='vary_hw', workload='ycsb', env='st'):
    
    # Read data from CSV
    csv_path = f'plots/data/{env}/{workload}/{plot}_resource_util.csv'
    data = pd.read_csv(csv_path)

    if plot == 'vary_hw':
        x_lab = 'VM Type'
    elif plot == 'server_skew':
        x_lab = 'Server Distribution'

    # Extract data
    xaxis_points = data['x_var']

    databases = ['Calvin', 'SLOG', 'Detock', 'Janus', 'CockroachDB']
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:brown']
    metrics = ['cpu_usage_percent', 'mem_usage_percent', 'net_usage_percent', 'disk_usage_percent', 'aborts']
    subplot_titles = ['CPU Util', 'Memory Util', 'Network Util', 'Disk Util', 'Aborts']
    y_labels = [
        'CPU Utilization (%)',
        'Memory Utilization (%)',
        'Network Utilization (%)',
        'Disk Utilization (%)',
        'Aborts (%)'
    ]

    # Create figure and subplots
    # Make the latency subplot wider to accomodate for the side by side bars
    if len(metrics) == 5:
        wr = [1, 1.5, 1, 1, 1]
    elif len(metrics) == 4:
        wr = [1, 1.5, 1, 1]
    fig, axes = plt.subplots(1, len(metrics), width_ratios=wr, figsize=(15, 2.5), sharex=True)

    # Configure Matplotlib global font size
    fs = 8
    plt.rcParams.update({
        'font.size': 12,        # Increase font size for better readability
        'axes.titlesize': 12,
        'axes.labelsize': 12,
        'xtick.labelsize': fs,
        'ytick.labelsize': fs,
        'legend.fontsize': 10
    })

    default_xaxis_points = [-2*BAR_WIDTH + x for x in range(len(xaxis_points))]
    for ax, metric, y_label, subplot_title in zip(axes, metrics, y_labels, subplot_titles):
        for db, color, i in zip(databases, colors, range(len(databases))):
            cur_x_axis_points = [x+i*BAR_WIDTH for x in default_xaxis_points]
            column_name = f'{db}_{metric}'
            if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                ax.bar(cur_x_axis_points, data[column_name.lower()], width=BAR_WIDTH, label=db, color=color, edgecolor='#000000')
        ax.set_title(subplot_title)
        ax.set_ylabel(y_label)
        ax.set_xlabel(x_lab)
        ax.set_ylim(0, 100)
        x = np.arange(len(xaxis_points))
        if plot == 'vary_hw':
            xaxis_points_final = [x[:-5] for x in xaxis_points]
        elif plot == 'server_skew':
            sever_skew_mappings = {'balanced': 'unif.',
                                   'us-west+': 'usw+',
                                   'us-west+_eu-west+': 'usw+\neu+',
                                   'us-west++': 'usw++',
                                   'us-west++_eu-west++': 'usw++\neu++',
                                   'us-west_only': 'usw only'}
            xaxis_points_final = [sever_skew_mappings[x] for x in xaxis_points]
        ax.set_xticks(x, xaxis_points_final, fontsize=fs)
        ax.grid(which='major', axis='y')

    # Add legend and adjust layout
    handles, labels = axes[-1].get_legend_handles_labels()
    labels = [l[:1].capitalize()+l[1:] for l in labels]
    fig.legend(handles, labels, loc='upper center', ncol=len(databases), bbox_to_anchor=(0.5, 1.1))
    fig.text(
        0.02, 0.5,                # (x, y) in figure coordinates — x=0.02 pushes it to the left
        f'{WORKLOAD_CAPITALIZATION[workload]} Resource\nUtilization',        # the label text
        va='center', ha='center', # center vertically
        rotation='vertical',      # vertical orientation
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout(rect=[0.03, 0, 1, 1])  # Further reduce whitespace

    # Save figures
    output_path = f'plots/output/{env}/{workload}/{plot}_{workload}_resource_util'
    png_path = output_path + '.png'
    pdf_path = output_path + '.pdf'
    os.makedirs('/'.join(output_path.split('/')[:-1]), exist_ok=True)
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.show()

def make_txn_type_ablations(plot='vary_hw', workload='ycsb', env='st', log_latencies=True):
    
    # Read data from CSV
    csv_path = f'plots/data/{env}/{workload}/{plot}_latency_ablations.csv'
    data = pd.read_csv(csv_path)

    if plot == 'baseline':
        x_lab = 'Geo-distribution (%)'
        x_lim = (0,100)
    elif plot == 'skew':
        x_lab = 'Skew factor (Theta)'
        x_lim = (0,1)
    elif plot == 'scalability':
        x_lab = 'Input Throughput (txn/s)'
        if workload == 'ycsb':
            if env == 'aws':
                x_lim = (0,200_000)
            else:
                x_lim = (0,50_000)
        elif workload == 'tpcc':
            x_lim = (0,50_000)
        elif workload == 'pps':
            x_lim = (0,150_000)
        elif workload == 'movie':
            x_lim = (0,150_000)
        elif workload == 'smallbank':
            x_lim = (0,100_000)
        elif workload == 'movr':
            x_lim = (0,35_000)
        elif workload == 'dsh':
            x_lim = (0,100_000)
    elif plot == 'network':
        x_lab = 'Extra delay (ms)'
        x_lim = (0,1000)
    elif plot == 'packet_loss':
        x_lab = 'Packets lost (%)'
        x_lim = (0,10)
    elif plot == 'sunflower':
        x_lab = 'Sunflower falloff'
    elif plot == 'example':
        x_lab = 'Example x-axis'

    # Extract data
    xaxis_points = data['x_var']
    if workload == 'tpcc' and plot == 'baseline':
        xaxis_points = [0, 4, 8, 15, 20, 25, 29, 32, 34, 36, 38, 39]
        if len(list(set(data['x_var']))) == 17: # Extended version of TPC-C with up to 88% FSH & MH
            #               0.00;0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.25;0.30;0.40;0.50;0.60;0.70;0.80;0.90;1.00]
            xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,52.4,56.0,61.4,66.1,70.4,74.6,79.1,83.6,88.0]
        elif len(list(set(data['x_var']))) == 16: # Detock and SLOG sometimes have no datapoint for 0% FSH & MH
            #               0.01;0.02;0.05;0.075;0.10;0.15;0.20;0.25;0.30;0.40;0.50;0.60;0.70;0.80;0.90;1.00]
            xaxis_points = [4.66,8.96,19.9,27.1, 33.0,42.0,48.0,52.4,56.0,61.4,66.1,70.4,74.6,79.1,83.6,88.0]
        crdb_baseline_tpcc_xaxis_points = [0,   4.66,8.96,19.9,27.1, 33.0,42.0,48.0,56.0,66.1,74.6,79.1,88.0]
        data['x_axis_points'] = xaxis_points
        xaxis_points = data['x_axis_points']
    elif workload == 'dsh' and plot == 'baseline':
        xaxis_points = [x * 100 for x in xaxis_points]

    fixed_percentile = '95'
    databases = ['Calvin', 'SLOG', 'Detock', 'Janus', 'CockroachDB']
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:brown']
    metrics = [f'read_p{fixed_percentile}', f'write_p{fixed_percentile}', 'latency']
    subplot_titles = ['Read Transactions', 'Write Transactions', 'LSH vs. FSH vs. MH']
    y_labels = [
        'Latency (ms)',
        'Latency (ms)',
        'Latency (ms)'
    ]

    # Create figure and subplots
    fig, axes = plt.subplots(1, len(metrics), figsize=(15, 2.5), sharex=True)

    for ax, metric, y_label, subplot_title in zip(axes, metrics, y_labels, subplot_titles):
        min_latency = 1_000_000_000
        for db, color in zip(databases, colors):
            if plot == 'scalability':
                column_name = f'{db}_input_throughput'
                if column_name.lower() in data.columns:
                    #xaxis_points = data[data[column_name.lower()].notnull()][column_name.lower()]
                    xaxis_points = data[column_name.lower()]
            column_name = f'{db}_{metric}'
            if subplot_title == 'LSH vs. FSH vs. MH':
                cur_colors = [lighten_color(color=color, factor=0.5), mcolors.to_rgb(color), darken_color(color=color, factor=0.5)]
                for txn_type, cur_color in zip(TXN_TYPES, cur_colors):
                    column_name = f'{db}_{txn_type}_p{fixed_percentile}'
                    if db.lower() == 'calvin' or db.lower() == 'janus':
                        cur_color = cur_colors[1] # Janus & Calvin do not differentiate between txn types
                        column_name = f'{db}_lsh_p{fixed_percentile}'
                    if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                        ax.plot(xaxis_points[data[column_name.lower()].notnull()], data[data[column_name.lower()].notnull()][column_name.lower()], label=db, color=cur_color) #, linestyle=style)
                        min_latency = min(min_latency, min(data[column_name.lower()]))
            else:
                if column_name.lower() in data.columns:  # Plot only if the column exists in the CSV
                    ax.plot(xaxis_points[data[column_name.lower()].notnull()], data[data[column_name.lower()].notnull()][column_name.lower()], label=db, color=color)
        ax.set_title(subplot_title)
        ax.set_ylabel(y_label)
        ax.set_xlabel(x_lab)
        if not log_latencies or (metric != 'latency' and 'read_p' not in metric and 'write_p' not in metric):
            ax.set_ylim(bottom=0)  # Remove extra whitespace below y=0
        else:
            ax.set_ylim(bottom=1)
        ax.set_yscale('log')
        ax.set_xlim(x_lim)
        ax.grid(True)

    if plot == 'scalability':
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x/1000:.0f}k'))

    # Add legend and adjust layout
    handles, labels = axes[-1].get_legend_handles_labels()
    labels = [l[:1].capitalize()+l[1:] for l in labels]
    handles_set = set()
    labels_set = set()
    filtered_handles = []
    filtered_labels = []
    for handle, label in zip(handles, labels):
        if label not in labels_set:
            labels_set.add(label)
            handles_set.add(handle)
            filtered_labels.append(label)
            filtered_handles.append(handle)
    fig.legend(filtered_handles, filtered_labels, loc='upper center', ncol=len(databases), bbox_to_anchor=(0.5, 1.1))
    fig.text(
        0.02, 0.5,                # (x, y) in figure coordinates — x=0.02 pushes it to the left
        f'{WORKLOAD_CAPITALIZATION[workload]} Latency\nAblations',        # the label text
        va='center', ha='center', # center vertically
        rotation='vertical',      # vertical orientation
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout(rect=[0.03, 0, 1, 1])  # Further reduce whitespace

    # Save figures
    output_path = f'plots/output/{env}/{workload}/{plot}_{workload}_latency_ablations'
    png_path = output_path + '.png'
    pdf_path = output_path + '.pdf'
    os.makedirs('/'.join(output_path.split('/')[:-1]), exist_ok=True)
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="System Evaluation Script")
    parser.add_argument("-p",  "--plot", default="baseline", choices=VALID_SCENARIOS, help="The name of the experiment we want to plot.")
    parser.add_argument("-w",  "--workload", default="ycsb", choices=VALID_WORKLOADS, help="The workload that was evaluated.")
    parser.add_argument('-e',  '--environment', default='aws', choices=VALID_ENVIRONMENTS, help='What type of machine the experiment was run on.')
    parser.add_argument("-sa", "--skip_aborts", default=False, help="Whether or not to plot the aborts (since many workloads don't have any).")
    parser.add_argument("-lp", "--latency_percentiles", default=DEFAULT_LAT_PERCENTILES, help="The latency percentiles to plot")
    parser.add_argument("-sl", "--separate_latencies", default=True, help="Whether or not to separate latencies by txn type.")
    parser.add_argument("-ll", "--log_latencies", default=True, help="Whether or not to plot the latency on a log scale.")
    parser.add_argument("-ct", "--costs_per_txn", default=True, help="Whether or not to plot the cost per transaction.")

    args = parser.parse_args()
    plot = args.plot
    workload = args.workload
    environment = args.environment
    skip_aborts = args.skip_aborts
    latency_percentiles = args.latency_percentiles
    separate_latencies = args.separate_latencies
    log_latencies = args.log_latencies
    costs_per_txn = args.costs_per_txn

    latencies = [int(latency) for latency in latency_percentiles.split(';')]

    make_plot(plot=plot,
              workload=workload,
              env=environment,
              latency_percentiles=latencies,
              skip_aborts=skip_aborts,
              separate_latencies=separate_latencies,
              log_latencies=log_latencies,
              costs_per_txn=costs_per_txn)

    print("Done")
