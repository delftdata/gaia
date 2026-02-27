#include <iostream>
#include <pqxx/pqxx>
#include <chrono>
#include <vector>
#include <thread>
#include <random>
#include <cmath>
#include <atomic>
#include <algorithm>
#include <iomanip>
#include <fstream>
#include <mutex>
#include <set>
#include <memory>
#include <sstream>

#include <glog/logging.h>

const int ROW_COUNT = 10000000;                  // 10M rows
const int HOT_SET_SIZE = 100000;                 // 100k rows (Hot)
const int ROWS_PER_PARTITION = 2500000;          // Updated for 10M rows / 4 nodes
const int NUM_PARTITIONS = 2;                    // 2 partitions
const int NUM_REGIONS = 2;                       // 2 regions
const int CRDB_PORT = 26257;
const int TXNS_TO_PREGEN = 2000000;              // Pre-generate 2M transactions
const int GENERATOR_THREADS = 2;                 // Number of threads
const std::string default_ip = "131.180.125.40"; // Default for ST environment
const std::string database_name = "geo_bench";

struct BenchParams {
    int num_threads = 4;
    int seconds = 60;
    double read_prop = 0.0; // Update only workload
    double zipf_skew = 0.0; // 0.0 means uniform, ~1.0 means highly skewed
    double multi_part_prob = 0.5;
    double multi_home_prob = 0.5;
    double sample_rate = 0.10; // Sample 10% for transactions.csv
    int num_partitions = NUM_PARTITIONS;
    int num_regions = NUM_REGIONS;
    int client_region = 0; // Default region for the client
    std::string workload_name = "ycsb"; // Default workload
};

struct Stats {
    std::vector<double> latencies;
    long committed = 0;
    long aborted = 0;
    long total_restarts = 0;
    long multi_home = 0;      // Across regions
    long multi_partition = 0; // Across nodes, same region
    long single_partition = 0;
};

struct PreGenTxn {
    std::string sql;
    bool is_multi_home;
    bool is_multi_partition;
    std::string txn_string; // For the local_log_buffer
    std::set<int> regions;
    std::set<int> partitions;

    // Explicit constructor to fix the push_back error
    PreGenTxn(std::string s, bool mh, bool mp, std::string ts, std::set<int> r, std::set<int> p) 
        : sql(s), is_multi_home(mh), is_multi_partition(mp), txn_string(ts), regions(r), partitions(p) {}
};

std::vector<PreGenTxn> global_txn_pool;

// Automatically detect local IP
std::string get_local_ip() {
    std::array<char, 128> buffer;
    std::string result;
    std::unique_ptr<FILE, decltype(&pclose)> pipe(popen("hostname -I | cut -d' ' -f1", "r"), pclose);
    if (!pipe) return "127.0.0.1";
    if (fgets(buffer.data(), buffer.size(), pipe.get()) != nullptr) {
        result = buffer.data();
    }
    // Remove newline
    result.erase(std::remove(result.begin(), result.end(), '\n'), result.end());
    return result;
}

// For thread-safe logging to transactions.csv
std::mutex log_mutex;
std::ofstream txn_log;

long long get_zipf_key(double skew, int max_val) {
    static thread_local std::mt19937 gen(std::random_device{}());
    std::uniform_real_distribution<double> dist(0.0001, 1.0);
    return static_cast<long long>(std::pow(dist(gen), 1.0 / (1.0 - skew)) * max_val) % max_val;
}

std::vector<long long> generate_keys_logic(const BenchParams& params, std::mt19937& gen) {
    std::uniform_real_distribution<double> coin(0.0, 1.0);
    std::vector<long long> keys;

    // Global layout constants
    long long keys_per_region = ROW_COUNT / params.num_regions;
    long long hot_per_region = HOT_SET_SIZE / params.num_regions;
    long long keys_per_partition = ROWS_PER_PARTITION;
    long long hot_per_partition = hot_per_region / params.num_partitions;
    long long home_region_start = (long long)params.client_region * keys_per_region;

    // Remote region setup
    std::vector<int> other_regions;
    for (int r = 0; r < params.num_regions; ++r) {
        if (r != params.client_region) other_regions.push_back(r);
    }
    
    std::uniform_int_distribution<int> remote_region_picker(0, std::max(0, (int)other_regions.size() - 1));
    std::uniform_int_distribution<int> local_partition_picker(0, params.num_partitions - 1);

    // 0. Determine Transaction Type
    bool is_multi_home = coin(gen) < params.multi_home_prob;
    bool is_multi_partition = coin(gen) < params.multi_part_prob;

    long long r_start = -1;
    long long partition_start = -1;

    if (is_multi_home) {
        int r_reg = other_regions[remote_region_picker(gen)];
        r_start = (long long)r_reg * keys_per_region;
    } else if (!is_multi_partition) {
        int partition = local_partition_picker(gen);
        partition_start = home_region_start + (partition * keys_per_partition);
    }

    // 1. HOT KEYS (2 total)
    if (is_multi_home) {
        // 1 Remote Hot
        keys.push_back(r_start + (params.zipf_skew == 0 ? 
            std::uniform_int_distribution<long long>(0, hot_per_region - 1)(gen) : 
            get_zipf_key(params.zipf_skew, hot_per_region)));
        // 1 Home Hot
        keys.push_back(home_region_start + (params.zipf_skew == 0 ? 
            std::uniform_int_distribution<long long>(0, hot_per_region - 1)(gen) : 
            get_zipf_key(params.zipf_skew, hot_per_region)));
    } else {
        long long start = is_multi_partition ? home_region_start : partition_start;
        long long range = is_multi_partition ? hot_per_region : hot_per_partition;
        for (int i = 0; i < 2; ++i) {
            keys.push_back(start + (params.zipf_skew == 0 ? 
                std::uniform_int_distribution<long long>(0, range - 1)(gen) : 
                get_zipf_key(params.zipf_skew, range)));
        }
    }

    // 2. COLD KEYS (8 total)
    if (is_multi_home) {
        // 4 Remote Cold
        for (int i = 0; i < 4; i++) {
            keys.push_back(r_start + hot_per_region + 
                std::uniform_int_distribution<long long>(0, keys_per_region - hot_per_region - 1)(gen));
        }
        // 4 Home Cold
        for (int i = 0; i < 4; i++) {
            keys.push_back(home_region_start + hot_per_region + 
                std::uniform_int_distribution<long long>(0, keys_per_region - hot_per_region - 1)(gen));
        }
    } else {
        long long start = is_multi_partition ? home_region_start : partition_start;
        long long h_size = is_multi_partition ? hot_per_region : hot_per_partition;
        long long total = is_multi_partition ? keys_per_region : keys_per_partition;
        for (int i = 0; i < 8; i++) {
            keys.push_back(start + h_size + 
                std::uniform_int_distribution<long long>(0, total - h_size - 1)(gen));
        }
    }

    return keys;
}

void pre_generate_workload(BenchParams& p) {
    LOG(INFO) << "Generating " << TXNS_TO_PREGEN << " transactions";
    std::mt19937 gen(42); 
    
    // Pre-calculate common strings to save CPU
    for (int i = 0; i < TXNS_TO_PREGEN; ++i) {
        // 1. Get the keys for this transaction
        std::vector<long long> keys = generate_keys_logic(p, gen); // Your existing logic
        
        // 2. Analyze footprint for stats
        std::set<int> nodes_hit;
        std::set<int> regions_hit;
        std::string txn_id_string = "SET";
        
        for(auto k : keys) {
            int node_id = k / ROWS_PER_PARTITION;
            int region_id = node_id / p.num_partitions;
            nodes_hit.insert(node_id);
            regions_hit.insert(region_id);
            txn_id_string += ";" + std::to_string(k);
        }
        txn_id_string += ";ZpHOk_RANDOM_DATA_" + std::to_string(keys[0] % 999);

        bool mh = (regions_hit.size() > 1);
        bool mp = (nodes_hit.size() > 1);

        // 3. Build Batch UPSERT SQL
        std::string sql = "UPSERT INTO usertable (ycsb_key, field0) VALUES ";
        for (int j = 0; j < 10; ++j) {
            sql += "(" + std::to_string(keys[j]) + ", 'thread_val_" + std::to_string(keys[j] % 1000) + "')";
            if (j < 9) sql += ", ";
        }

        // 4. Push to pool using the constructor
        global_txn_pool.emplace_back(sql, mh, mp, txn_id_string, regions_hit, nodes_hit);
        
        if (i % 100000 == 0) LOG(INFO) << "Current txn counts: Total: " << i;
    }
    LOG(INFO) << "Pre-generation complete.";
}

void worker(int id, std::string conn_str, BenchParams params, std::atomic<bool>& running, Stats& stats) {
    try {
        pqxx::connection c{conn_str};
        size_t pool_idx = id; 
        std::string local_log_buffer;

        while (running) {
            const auto& txn_data = global_txn_pool[pool_idx % global_txn_pool.size()];
            auto sent_at = std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();

            try {
                pqxx::work txn{c};
                // txn_data.sql already contains the full "UPSERT INTO ... VALUES (...), (...)" string
                // We just execute it once per transaction.
                txn.exec(txn_data.sql);
                txn.commit();

                auto received_at = std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count();

                // Record stats using pre-baked flags
                stats.committed++;
                if (txn_data.is_multi_home) stats.multi_home++;
                else if (txn_data.is_multi_partition) stats.multi_partition++;
                else stats.single_partition++;

                stats.latencies.push_back((received_at - sent_at) / 1000000.0);
                
                // Add the pre-baked log entry to our local buffer
                std::string regions_str;
                std::stringstream regions_ss;
                for (auto it = txn_data.regions.begin(); it != txn_data.regions.end(); ++it) {
                    if (it != txn_data.regions.begin()) {
                        regions_ss << ";";
                    }
                    regions_ss << *it;
                }
                regions_str = regions_ss.str();

                std::string partitions_str;
                std::stringstream partitions_ss;
                for (auto it = txn_data.partitions.begin(); it != txn_data.partitions.end(); ++it) {
                    if (it != txn_data.partitions.begin()) {
                        partitions_ss << ";";
                    }
                    partitions_ss << *it;
                }
                partitions_str = partitions_ss.str();
                std::string line = "";
                line += std::to_string(pool_idx) + ",";    // txn_id (using pool_idx as txn_id)
                line += "-1,";                             // coordinator
                line += regions_str + ",";                 // regions
                line += partitions_str + ",";              // partitions
                line += "0,";                              // generator
                line += "0,";                              // restarts
                line += std::to_string(pool_idx) + ",";    // global_log_pos
                line += std::to_string(sent_at) + ",";     // sent_at
                line += std::to_string(received_at) + ","; // received_at
                line += txn_data.txn_string + "\n";        // code
                local_log_buffer += line;

            } catch (const pqxx::serialization_failure &e) {
                stats.total_restarts++;
            } catch (const std::exception &e) {
                stats.aborted++;
            }
            pool_idx += params.num_threads;
        }
        // Flush logs once at the end
        std::lock_guard<std::mutex> lock(log_mutex);
        txn_log << local_log_buffer;
    } catch (const std::exception &e) {
        std::cerr << "Thread " << id << " error: " << e.what() << std::endl;
    }
}

int main(int argc, char* argv[]) {
    google::InitGoogleLogging(argv[0]);
    FLAGS_logtostderr = 1; // To make logs show on console

    if (argc < 2) {
        LOG(INFO) << "Usage: ./benchmark_crdb <IP> <threads> <read_%> <skew> <multi_part_%> <multi_home_%> <num_partitions> <num_regions> <seconds> <client_region>";
        return 1;
    }

    BenchParams p;
    std::string ip = default_ip; // Note, the Docker container will have its own IP, so we need to pass the host IP as argument
    p.num_partitions = NUM_PARTITIONS;
    p.num_regions = NUM_REGIONS;
    LOG(INFO) << "Detected IP is: " << ip;

    // 1. Argument Parsing
    if (argc > 1) ip = argv[1];
    if (argc > 2) p.num_threads = std::stoi(argv[2]);
    if (argc > 3) p.read_prop = std::stod(argv[3]);
    if (argc > 4) p.zipf_skew = std::stod(argv[4]);
    if (argc > 5) p.multi_part_prob = std::stod(argv[5]);
    if (argc > 6) p.multi_home_prob = std::stod(argv[6]);
    if (argc > 7) p.num_partitions = std::stoi(argv[7]);
    if (argc > 8) p.num_regions = std::stoi(argv[8]);
    if (argc > 9) p.seconds = std::stoi(argv[9]);
    if (argc > 10) p.client_region = std::stoi(argv[10]);
    if (argc > 11) p.workload_name = argv[11];

    // 2. Pre-generation (Crucial step)
    pre_generate_workload(p);
    if (global_txn_pool.empty()) {
        LOG(ERROR) << "Workload pool is empty. Check pre_generate_workload logic.";
        return 1;
    }

    // 3. Initialize Logs
    txn_log.open("transactions.csv");
    txn_log << "txn_id,coordinator,regions,partitions,generator,restarts,global_log_pos,sent_at,received_at,code\n";

    std::string conn_str = "postgresql://root@" + ip + ":" + std::to_string(CRDB_PORT) + "/" + database_name + "?sslmode=disable";
    std::atomic<bool> running{true};
    std::vector<Stats> all_stats(p.num_threads);
    std::vector<std::thread> threads;

    // 4. Start Worker(s)
    LOG(INFO) << "Start sending transactions with: " << p.num_threads << " threads, Skew: " << p.zipf_skew << ", MP: " << p.multi_part_prob << ", MH: " << p.multi_home_prob 
        << ", Num partitions: " << p.num_partitions << ", Num regions: " << p.num_regions << ", Seconds: " << p.seconds << std::endl;
    auto start_time = std::chrono::high_resolution_clock::now();

    for (int i = 0; i < p.num_threads; ++i) {
        threads.emplace_back(worker, i, conn_str, p, std::ref(running), std::ref(all_stats[i]));
    }

    // 5. Execution and Teardown
    std::this_thread::sleep_for(std::chrono::seconds(p.seconds));
    running = false;
    for (auto& t : threads) t.join();

    auto end_time = std::chrono::high_resolution_clock::now();
    auto total_elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end_time - start_time).count();

    LOG(INFO) << "Finished benchmark. " << std::endl;

    // 6. Aggregation for Summary
    long committed = 0, aborted = 0, restarts = 0, mp = 0, sp = 0, mh = 0;
    std::vector<double> combined_latencies;
    for (auto& s : all_stats) {
        committed += s.committed;
        aborted += s.aborted;
        restarts += s.total_restarts;
        mh += s.multi_home;
        mp += s.multi_partition;
        sp += s.single_partition;
        combined_latencies.insert(combined_latencies.end(), s.latencies.begin(), s.latencies.end());
    }
    std::sort(combined_latencies.begin(), combined_latencies.end());

    // 7. CSV Generation (Summary, Metadata, Events)
    // Generate summary.csv
    std::ofstream summary("summary.csv");
    summary << "committed,aborted,not_started,restarted,single_home,foreign_single_home,multi_home,single_partition,multi_partition,remaster,elapsed_time\n";
    summary << committed << "," << aborted << ",0," << restarts << "," << (committed - mh) << ",0," << mh << "," 
            << sp << "," << mp << ",0," << total_elapsed_ns << "\n";
    summary.close();

    // Generate metadata.csv
    std::ofstream metadata("metadata.csv");
    metadata << "duration,txns,clients,rate,sample,wl:name,wl:mh,wl:mh_homes,wl:writes,wl:nearest,wl:mh_zipf,wl:mp_parts,wl:mp,wl:hot,wl:records,wl:hot_records,wl:value_size,wl:sp_partition,wl:sh_home,wl:hot_zipf\n";

    metadata << p.seconds << "," << "-1" << "," << p.num_threads << "," << "-1" << ",-1," << p.workload_name << "," 
            << p.multi_home_prob << "," << 1.0 << "," << 1.0 - p.multi_part_prob << "," 
            << 1.0 - p.multi_home_prob * p.multi_part_prob * 2.0 / 3.0 /* nearest */<< "," 
            << p.zipf_skew * 2.5 /* mh_zipf */<< "," 
            << p.multi_part_prob * 2.5 /* mp_parts */<< ","
            << p.multi_part_prob * 2.5 /* mp */<< ","
            << "-1" << ","
            << "-1" << ","
            << "-1" << ","
            << "-1" << ","
            << "-1" << ","
            << "-1" << ","
            << "-1" <<"\n";
    metadata.close();

    // Generate txn_events.csv
    std::ofstream txn_events("txn_events.csv");
    txn_events << "txn_id,event,time,machine,home\n";
    txn_events.close();

    LOG(INFO) << std::fixed << std::setprecision(2);
    LOG(INFO) << "\n--- RESULTS ---";
    LOG(INFO) << "Avg. TPS: " << (double)committed / (total_elapsed_ns / 1000000000.0);
    if (!combined_latencies.empty()) {
        LOG(INFO) << "P50 Latency: " << combined_latencies[combined_latencies.size() * 0.50] << " ms";
        LOG(INFO) << "P99 Latency: " << combined_latencies[combined_latencies.size() * 0.99] << " ms";
    }
    LOG(INFO) << "Results were written to 'summary.csv' and 'transactions.csv'.";

    return 0;
}
