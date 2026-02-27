# 2. Build CockroachDB & create Docker image
# Use the explicit path to your newly installed bazel (bazelisk)
BAZEL=/usr/local/bin/bazel ./dev build short -- --define=oss=true

cp ~/Detock/crdb/Dockerfile_crdb_compile ./Dockerfile
docker build -t omraz/seq_eval:crdb-custom .
docker push omraz/seq_eval:crdb-custom

# You can later run the image with the following command. This starts a single-node insecure cluster:
# docker run -d --name crdb-test -p 26257:26257 -p 8080:8080 omraz/seq_eval:crdb-custom start-single-node --insecure

# You might need to pull the image first if not present locally:
# docker pull omraz/seq_eval:crdb-custom

# You can enter the SQL shell with:
# docker exec -it crdb-test ./cockroach sql --insecure

# To stop the container:
# docker stop crdb-test

# Note: For multi-region clusters you need to set a Enterprise license key
# SET CLUSTER SETTING cluster.organization = '';
# SET CLUSTER SETTING enterprise.license = '...';