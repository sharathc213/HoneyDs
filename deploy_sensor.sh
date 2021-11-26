#!/bin/sh
# Install
echo -e "\e[93mInstalling HoneyDS Sensor \e[0m" ; sleep 5
apt update
apt install -y python-setuptools python-pcapy git schedtool
cd /tmp
git clone --depth 1 https://github.com/sharathc213/HoneyDs.git
mv /tmp/honeyds /opt
chown -R $USER:$USER /opt/honeyds
# Set working environment
mkdir -p /var/log/honeyds
mkdir -p /etc/honeyds
#Add Remote Server:port IP
read -p 'SERVER_IP: ' ip
#echo "LOG_SERVER $ip:1019" >> /opt/honeyds/honeyds.conf
sed -i "97i\LOG_SERVER $ip:1019" /opt/honeyds/honeyds.conf
cp /opt/honeyds/honeyds.conf /etc/honeyds
# Adding cron job
echo -e "\e[93mUpdating cron job to autostart sensor & periodic restart \e[0m"
crontab <<EOF
*/1 * * * * if [ -n "$(ps -ef | grep -v grep | grep 'sensor.py')" ]; then : ; else python /opt/honeyds/sensor.py -c /etc/honeyds/honeyds.conf; fi
2 1 * * * /usr/bin/pkill -f honeyds
EOF
#python /opt/honeyds/sensor.py -c /etc/honeyds/honeyds.conf &
echo -e "\e[93mSensor Deployment Finished \e[0m"
echo -e "\e[93m $(tail -n 2  /var/log/honeyds/$(date +"%Y-%m-%d").log)"
echo -e "\e[93mCheck Dashboard \e[0m"
