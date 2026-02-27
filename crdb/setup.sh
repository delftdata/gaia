# Script to download necessary package and CockroachDB itself

# Clone repo and checkout a stable branch
git clone https://github.com/cockroachdb/cockroach.git
cd cockroach
git checkout v23.1.0

# General build tools
sudo apt-get update
sudo apt-get install -y build-essential pkg-config wget git

# CockroachDB specific C-dependencies (even for OSS builds)
sudo apt-get install -y libkrb5-dev libedit-dev libncurses-dev

# Bazelisk (to manage the Bazel build system)
wget https://github.com/bazelbuild/bazelisk/releases/download/v1.19.0/bazelisk-linux-amd64
chmod +x bazelisk-linux-amd64
sudo mv bazelisk-linux-amd64 /usr/local/bin/bazel

# Remove missing dependencies that are not needed for OSS build:
# Bypass the lresolv_wrapper linker error and strip out Enterprise CCL features
cat <<EOF > pkg/ccl/gssapiccl/BUILD.bazel
load("@io_bazel_rules_go//go:def.bzl", "go_library")

go_library(
    name = "gssapiccl",
    srcs = ["empty.go"],
    importpath = "github.com/cockroachdb/cockroach/pkg/ccl/gssapiccl",
    visibility = ["//visibility:public"],
    deps = [],
)
EOF

# Ensure the stub file exists:
echo "package gssapiccl" > pkg/ccl/gssapiccl/empty.go
