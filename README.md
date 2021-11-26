# HoneyDS



## Deploying server

```
sudo su
cd /tmp/ && wget https://gitlab.com/Abdu007/honey-ds/-/raw/master/deploy_server.sh && bash deploy_server.sh

```

## Deploying sensor

```

sudo su
cd /tmp/ && wget https://gitlab.com/Abdu007/honey-ds/-/raw/master/deploy_sensor.sh && bash deploy_sensor.sh

```


To stop Sensor and Server instances (if running in background) execute the following:

```
sudo pkill -f sensor.py
pkill -f server.py

```


