#
# Zookeeper client node demo container image
#

FROM ghcr.io/maxotta/kiv-ds-docker:latest

RUN yum -q -y install python3
RUN pip3 install kazoo requests Flask

COPY python /opt/zk/client
RUN ln -s /opt/zk/client/cli.py /usr/bin/kv-cli && chmod +x /usr/bin/kv-cli

CMD python3 /opt/zk/client/kvstore.py

# EOF
