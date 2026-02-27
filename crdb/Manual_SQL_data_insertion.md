consolidated set of SQL commands to manually set up your geodistributed YCSB environment. This sequence ensures a clean schema, partitioned data, and pinned leaseholders for a 4-node, 2-region cluster.

1. Schema Reset & Population
Run these to ensure you are starting with the BIGINT primary key and 5 test rows.

<code>-- Clean up existing data
DROP TABLE IF EXISTS usertable CASCADE;
-- Create the 2-column research schema
CREATE TABLE usertable (
    ycsb_key BIGINT PRIMARY KEY,
    field0 BYTES
);
-- Insert 5 baseline rows
INSERT INTO usertable (ycsb_key, field0) VALUES 
(1, '\x0123456789abcdef'),
(2, '\xdeadbeef12345678'),
(3, '\xabcdef0123456789'),
(4, '\x1234567890abcdef'),
(5, '\xfeedface00000000');<code>


2. Logical Partitioning
This splits the table into 4 buckets. Note that since we are using BIGINT, we do not use quotes around the numbers.

<code>-- Split the table into 4 logical partitions
ALTER TABLE usertable PARTITION BY RANGE (ycsb_key) (
    PARTITION p1 VALUES FROM (MINVALUE) TO (2),
    PARTITION p2 VALUES FROM (2) TO (3),
    PARTITION p3 VALUES FROM (3) TO (5),
    PARTITION p4 VALUES FROM (5) TO (MAXVALUE)
);<code>

3. Physical Locality & Zoning
These commands map the logical partitions to physical regions. We use num_replicas = 3 to satisfy the v23.1 validator.

<code>-- Partition 1 & 2: Home in West (usw)
ALTER PARTITION p1 OF TABLE usertable CONFIGURE ZONE USING 
    num_replicas = 3,
    lease_preferences = '[[+region=usw]]', 
    constraints = '{+region=usw: 2, +region=euw: 1}';

ALTER PARTITION p2 OF TABLE usertable CONFIGURE ZONE USING 
    num_replicas = 3,
    lease_preferences = '[[+region=usw]]', 
    constraints = '{+region=usw: 2, +region=euw: 1}';

-- Partition 3 & 4: Home in East (euw)
ALTER PARTITION p3 OF TABLE usertable CONFIGURE ZONE USING 
    num_replicas = 3,
    lease_preferences = '[[+region=euw]]', 
    constraints = '{+region=euw: 2, +region=usw: 1}';

ALTER PARTITION p4 OF TABLE usertable CONFIGURE ZONE USING 
    num_replicas = 3,
    lease_preferences = '[[+region=euw]]',
    constraints = '{+region=euw: 2, +region=usw: 1}';<code>


4. Verification
Use these two commands to confirm the data has finished moving. Range migration is an asynchronous background process, so you may need to run these twice.

Check physical placement:

<code>SELECT 
    range_id, 
    lease_holder, 
    lease_holder_locality, 
    replicas, 
    replica_localities 
FROM [SHOW RANGES FROM TABLE usertable];<code>

Check node-to-IP mapping (to verify which node is which IP):

<code>SELECT node_id, address, locality FROM crdb_internal.gossip_nodes;<code>

Summary of What This Achieves:

a) Primary Copy: Each region acts as the "Master" for its own range of keys.

b) Fault Tolerance: Every row has a copy on the other side of the world.

c) Benchmarking Fairness: This setup is the most direct comparison to Detock/SLOG because it tests "Home" vs "Remote" latencies explicitly.