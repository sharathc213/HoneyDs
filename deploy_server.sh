#!/bin/sh
# Install
echo -e "\e[93mInstalling HoneyDS Server \e[0m" ; sleep 5
apt update
apt install -y python-setuptools python-pcapy git schedtool sha256sum
cd /tmp
git clone --depth 1 https://gitlab.com/Abdu007/honey-ds.git
mv /tmp/honeyds /opt
chown -R $USER:$USER /opt/honeyds
# Set working environment
mkdir -p /var/log/honeyds
mkdir -p /etc/honeyds

cp /opt/honeyds/honeyds.conf /etc/honeyds
# Adding cron job
echo -e "\e[93mUpdating cron job to autostart sensor & periodic restart \e[0m"
crontab <<EOF
*/1 * * * * if [ -n "$(ps -ef | grep -v grep | grep 'server.py')" ]; then : ; else python /opt/honeyds/server.py -c /etc/honeyds/honeyds.conf; fi
0 1 * * * cd /opt/honeyds && git pull
EOF

echo -e "\e[93mDeployment Completed \e[0m"
echo -e "\e[93m $(tail -n 2  /var/log/honeyds/$(date +"%Y-%m-%d").log)"
echo -e "\e[93mBrowse http://0.0.0.0:1020 (default credentials: admin:admin)\e[0m"
