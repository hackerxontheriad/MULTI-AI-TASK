FROM kalilinux/kali-rolling
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    bash ca-certificates file binutils binwalk yara ripgrep jq unzip zip \
    python3 python3-pip python3-venv nmap strings coreutils findutils \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
CMD ["/bin/bash"]
