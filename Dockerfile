FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        kali-linux-headless \
        kali-tools-top10 \
        kali-tools-web \
        kali-tools-fuzzing \
        kali-tools-passwords \
        libcap2-bin \
        seclists \
        wordlists \
        bash-completion \
        ca-certificates \
        curl \
        dnsutils \
        git \
        gzip \
        iproute2 \
        iputils-ping \
        jq \
        less \
        net-tools \
        netcat-traditional \
        nmap \
        python3 \
        python3-pip \
        socat \
        telnet \
        tmux \
        traceroute \
        unzip \
        vim \
        whois \
        # AD/Kerberos tooling
        krb5-user \
        sshpass \
        ntpsec-ntpdate \
        faketime \
        # PWN/binary analysis (cross-arch on ARM host)
        patchelf \
        qemu-user-static \
        binutils-x86-64-linux-gnu \
        # Recon & misc
        nuclei \
        poppler-utils \
        xfsprogs \
    && (setcap -r /usr/lib/nmap/nmap 2>/dev/null; true) \
    && (setcap -r /usr/bin/nmap 2>/dev/null; true) \
    && if [ -f /usr/share/wordlists/rockyou.txt.gz ] && [ ! -f /usr/share/wordlists/rockyou.txt ]; then gzip -dk /usr/share/wordlists/rockyou.txt.gz; fi \
    && rm -rf /var/lib/apt/lists/*

# x86_64 libc for cross-arch binary analysis (ARM host with qemu-user-static)
RUN dpkg --add-architecture amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends libc6:amd64 \
    && rm -rf /var/lib/apt/lists/*

# mitmproxy + requests already provided by kali-tools-web
# pymssql + pypsrp provided by kali metapackages

# Python tools not in kali repos
RUN pip3 install --no-cache-dir --break-system-packages \
        pwntools \
        bloodhound \
        git-dumper \
        anthropic \
        opentelemetry-api \
        opentelemetry-sdk \
        opentelemetry-exporter-otlp-proto-grpc

# Copy MCP server entry point and modules
COPY mcp_server.py /opt/mcp_server.py
COPY src /opt/src

WORKDIR /workspace

# Keep container running with tail -f /dev/null (infinite loop)
CMD ["tail", "-f", "/dev/null"]
