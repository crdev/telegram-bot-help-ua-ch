envsubst < haproxy.cfg.template > /etc/haproxy/haproxy.cfg
/etc/init.d/haproxy restart
python3 bot.py
