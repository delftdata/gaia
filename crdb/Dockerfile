FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# --- Base system & build tools ---
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    pkg-config \
    wget \
    curl \
    ca-certificates \
    libpq-dev \
    libpqxx-dev \
    libgoogle-glog-dev \
    libgflags-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Working directory ---
WORKDIR /app

# --- Copy source ---
COPY . .

# --- Build ---
# Adjust path if needed
RUN g++ -std=c++17 benchmark_crdb.cpp \
    -o benchmark_crdb \
    -lpqxx -lpq -lglog -lgflags -pthread

# --- Default runtime flags ---
ENV GLOG_logtostderr=1

CMD ["./benchmark_crdb"]
