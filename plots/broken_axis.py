import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib import colors as mcolors
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
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

def make_broken_scalability_plot(workload='tpcc'):
    # --- 1. CONFIGURATION ---
    databases = ['Calvin', 'SLOG', 'Detock', 'Janus', 'CockroachDB']
    #line_styles = ['-', '--', '-.', ':', (0, (3, 5, 1, 5))]
    line_styles = ['-', '--', '-.', ':', (1, (1,1)), (0, (3, 1, 1, 1, 1, 1))]
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:brown']
    
    metrics = ['throughput', 'latency', 'bytes', 'cost']
    y_labels = [
        'Throughput\n(txn/s)',
        'Latency (ms)',
        'Data transfers\n(GB/s)',
        'Cost per\n10k txns (¢)'
    ]
    
    # Range configuration for the split axis
    x_break_low = 3000    # Where the first half ends
    x_break_high = 10000  # Where the second half starts
    
    csv_path = f'plots/data/aws/{workload}/scalability.csv'
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return

    data = pd.read_csv(csv_path)

    # --- 2. FIGURE SETUP ---
    plt.rcParams.update({
        'font.size': 11,
        'axes.titlesize': 11,
        'axes.labelsize': 10,
        'legend.fontsize': 10
    })
    
    # We create 1 row of 5 metric groups
    fig = plt.figure(figsize=(15, 2))
    outer_gs = GridSpec(1, 4, figure=fig, wspace=0.6)

    legend_handles = []
    legend_labels = []

    # --- 3. PLOTTING LOOP ---
    for i, (metric, y_label) in enumerate(zip(metrics, y_labels)):
        # Split each metric into a Left (larger) and Right (smaller) piece
        inner_gs = GridSpecFromSubplotSpec(1, 2, subplot_spec=outer_gs[i], 
                                         wspace=0.1, width_ratios=[1, 3])
        
        ax_left = fig.add_subplot(inner_gs[0])
        ax_right = fig.add_subplot(inner_gs[1])
        
        # Create twin axes for CockroachDB on BOTH halves
        ax_left_twin = ax_left.twinx()
        ax_right_twin = ax_right.twinx()

        for db, color, style in zip(databases, colors, line_styles):
            x_col = f'{db}_input_throughput'.lower()
            y_col = f'{db}_p99'.lower() if metric == 'latency' else f'{db}_{metric}'.lower()
            
            if x_col not in data.columns or y_col not in data.columns:
                continue

            # Filter out NaNs so the line connects properly
            valid_mask = data[y_col].notnull() & data[x_col].notnull()            
            x_vals = data.loc[valid_mask, x_col]
            y_vals = data.loc[valid_mask, y_col]
            if metric == 'bytes':
                y_vals = y_vals / 1_000_000_000 # Convert to GB

            ## Logic: Use the twin axis ONLY for CockroachDB
            #curr_l, curr_r = (ax_left_twin, ax_right_twin) if db == 'CockroachDB' else (ax_left, ax_right)
            #
            ## Plot on both halves (clipping handles the "gap")
            #line, = curr_l.plot(x_vals, y_vals, color=color, linestyle=style, label=db)
            #curr_r.plot(x_vals, y_vals, color=color, linestyle=style)
            # --- THE KEY FIX ---
            # We plot the EXACT SAME data on both the left and right subplots.
            # Matplotlib's 'xlim' will handle the "clipping" at the break automatically.
            
            # Choose the Y-axis (Twin for CRDB, Main for others)
            curr_l_y, curr_r_y = (ax_left_twin, ax_right_twin) if db == 'CockroachDB' else (ax_left, ax_right)
            line, = curr_l_y.plot(x_vals, y_vals, color=color, linestyle=style, label=db, clip_on=True)
            
            curr_r_y.plot(x_vals, y_vals, color=color, linestyle=style, clip_on=True)

            if i == 0: # Collect legend info from the first metric group
                legend_handles.append(line)
                legend_labels.append(db)

        # --- 4. THE "BROKEN AXIS" STYLING ---
        # Set X limits
        ax_left.set_xlim(0, x_break_low)
        ax_right.set_xlim(x_break_high, 60_000) #data.filter(like='input_throughput').max().max() * 1.1)
        
        # Log Scale for Latency
        if metric == 'latency':
            for a in [ax_left, ax_right, ax_left_twin, ax_right_twin]: a.set_yscale('log')

        # Add grids to both halves
        ax_left.grid(True)
        ax_right.grid(True)

        # Hide vertical spines between halves
        ax_left.spines['right'].set_visible(False)
        ax_right.spines['left'].set_visible(False)
        ax_right.yaxis.set_visible(False) # Hide the shared Y ticks on the right
        
        # Hide internal twin Y-axis ticks
        ax_left_twin.yaxis.set_visible(False)
        ax_right_twin.spines['left'].set_visible(False)
        
        # Break marks
        d = .02 
        kwargs = dict(transform=ax_left.transAxes, color='k', clip_on=False, lw=1)
        ax_left.plot((1-d, 1+d), (-d, +d), **kwargs)     
        ax_left.plot((1-d, 1+d), (1-d, 1+d), **kwargs) 
        kwargs.update(transform=ax_right.transAxes)
        ax_right.plot((-d/3, d/3), (-d, +d), **kwargs) 
        ax_right.plot((-d/3, d/3), (1-d, 1+d), **kwargs)

        # Format Ticks
        ax_left.set_ylabel(y_label)
        ax_left.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1000:.0f}k'))
        #ax_right.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1000:.0f}k'))
        
        if metric == 'throughput':
            ax_left.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1000:.0f}k'))
            ax_right_twin.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1000:.0f}k'))

        # Add individual x-labels for every subplot
        # We use a trick: place the text in the middle of the GridSpec cell
        fig.text(outer_gs[i].get_position(fig).x0 + outer_gs[i].get_position(fig).width/2, 
                 0.05, 'Input Throughput (txns/s)', ha='center', fontsize=10)

        if metric == 'cost':
            ax_left.set_ylim(0, 10)
            ax_right.set_ylim(0, 10)
            ax_left_twin.set_ylim(0, 50)
            ax_right_twin.set_ylim(0, 50)

        # Add "CRDB Scale" label to the very last twin axis
        #if i == len(metrics) - 1:
        #    ax_right_twin.set_ylabel('CRDB Scale', color='tab:brown', fontweight='bold', fontsize=10)

    # --- 5. FINISHING TOUCHES ---
    #fig.text(0.5, 0.02, 'Input Throughput (txn/s)', ha='center', fontsize=12, fontweight='bold')
    fig.legend(legend_handles, legend_labels, loc='upper center', 
               ncol=len(databases), bbox_to_anchor=(0.5, 1.1))

    #plt.tight_layout(rect=[0.04, 0, 1, 1])  # Further reduce whitespace
    plt.subplots_adjust(bottom=0.25)

    output_path = f'plots/output/aws/{workload}/scalability_ycsb_broken_x'
    png_path = output_path + '.png'
    pdf_path = output_path + '.pdf'
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.show()

def make_broken_yaxis_scalability_plot(workload='tpcc'):
    # --- 1. CONFIGURATION ---
    databases = ['Calvin', 'SLOG', 'Detock', 'Janus', 'CockroachDB']
    line_styles = ['-', '--', '-.', ':', (1, (1,1)), (0, (3, 1, 1, 1, 1, 1))]
    colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red', 'tab:brown']
    
    metrics = ['throughput', 'latency', 'bytes', 'cost']
    y_labels = [
        'Throughput\n(txn/s)',
        'Latency (ms)',
        'Data transfers\n(GB/s)',
        'Cost per\n10k txns (¢)'
    ]
    
    # Range configuration for the split axis
    y_break_low = 500    # Where the first half ends
    y_break_high = 10000  # Where the second half starts
    
    csv_path = f'plots/data/aws/{workload}/scalability.csv'
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return

    data = pd.read_csv(csv_path)

    # --- 2. FIGURE SETUP ---    
    plt.rcParams.update({'font.size': 11, 'axes.titlesize': 11, 'axes.labelsize': 10, 'legend.fontsize': 10})
    fig = plt.figure(figsize=(15, 2))
    outer_gs = GridSpec(1, 4, figure=fig, wspace=0.6)

    legend_handles = []
    legend_labels = []

    # --- 3. PLOTTING LOOP ---
    for i, (metric, y_label) in enumerate(zip(metrics, y_labels)):
        # Decide if we break the axis
        should_break = (metric != 'latency')

        if should_break:
            inner_gs = GridSpecFromSubplotSpec(2, 1, subplot_spec=outer_gs[i], hspace=0.08, height_ratios=[1, 2])
            ax_top = fig.add_subplot(inner_gs[0])
            ax_bot = fig.add_subplot(inner_gs[1])
            plot_axes = [ax_top, ax_bot]
        else:
            # Latency gets a single subplot covering the whole GridSpec slot
            ax_single = fig.add_subplot(outer_gs[i])
            plot_axes = [ax_single]
        
        for db, color, style in zip(databases, colors, line_styles):
            x_col = f'{db}_input_throughput'.lower()
            y_col = f'{db}_p99'.lower() if metric == 'latency' else f'{db}_{metric}'.lower()
            
            if x_col not in data.columns or y_col not in data.columns: continue

            valid = data[y_col].notnull() & data[x_col].notnull()            
            x_vals, y_vals = data.loc[valid, x_col], data.loc[valid, y_col]
            if metric == 'bytes': y_vals /= 1e9

            # Plot on all axes in the current slot (clipping handles the rest)
            for ax in plot_axes:
                line, = ax.plot(x_vals, y_vals, color=color, ls=style)

            if i == 0:
                legend_handles.append(line); legend_labels.append(db)

        # --- 4. STYLING & BREAK MARKS ---
        # Define scale ranges
        if metric == 'throughput':
            y_low_max, y_high_min, y_max = 500, 10000, 45000
        elif metric == 'bytes':
            y_low_max, y_high_min, y_max = 0.05, 0.1, 1.5
        elif metric == 'cost':
            y_low_max, y_high_min, y_max = 5, 5, 60
        else: # Latency (unbroken)
            y_max = 10_000


        if should_break:
            ax_top.set_ylim(y_high_min, y_max)
            ax_bot.set_ylim(0, y_low_max)
            
            # Formatting
            ax_top.spines['bottom'].set_visible(False)
            ax_bot.spines['top'].set_visible(False)
            ax_top.xaxis.set_visible(False)
            ax_top.grid(True, ls=':', alpha=0.5)
            ax_bot.grid(True, ls=':', alpha=0.5)

            # Break marks
            d = .02
            kwargs = dict(transform=ax_top.transAxes, color='k', clip_on=False, lw=1)
            ax_top.plot((-d, +d), (-d, +d), **kwargs)        
            ax_top.plot((1-d, 1+d), (-d, +d), **kwargs)    
            kwargs.update(transform=ax_bot.transAxes)
            ax_bot.plot((-d, +d), (1-d, 1+d), **kwargs)    
            ax_bot.plot((1-d, 1+d), (1-d, 1+d), **kwargs)
            
            main_ax = ax_bot # Reference for shared labels
        else:
            ax_single.set_yscale('log')
            ax_single.set_ylim(1, y_max)
            ax_single.grid(True, ls=':', alpha=0.5, which='both')
            main_ax = ax_single

        # Shared Formatting
        for ax in plot_axes:
            ax.set_xlim(0, 60000)
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1000:.0f}k'))
            if metric == 'throughput':
                ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f'{x/1000:.0f}k'))

        # Centered Y-label
        fig.text(outer_gs[i].get_position(fig).x0 - 0.06, 
                 outer_gs[i].get_position(fig).y0 + outer_gs[i].get_position(fig).height/2, 
                 y_label, va='center', rotation='vertical', fontsize=10)
        
        main_ax.set_xlabel('Input Throughput (txn/s)')

    # --- 5. FINISHING TOUCHES ---
    #fig.text(0.5, 0.02, 'Input Throughput (txn/s)', ha='center', fontsize=12, fontweight='bold')
    fig.legend(legend_handles, legend_labels, loc='upper center', 
               ncol=len(databases), bbox_to_anchor=(0.5, 1.1))

    #plt.tight_layout(rect=[0.04, 0, 1, 1])  # Further reduce whitespace
    plt.subplots_adjust(bottom=0.25)

    output_path = f'plots/output/aws/{workload}/scalability_ycsb_broken_x'
    png_path = output_path + '.png'
    pdf_path = output_path + '.pdf'
    plt.savefig(png_path, dpi=300, bbox_inches='tight')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.show()

#make_broken_scalability_plot(workload='tpcc')
make_broken_yaxis_scalability_plot(workload='tpcc')

print("Done")