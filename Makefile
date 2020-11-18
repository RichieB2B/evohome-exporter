LIB:=evohome-exporter.py keys.py

install: $(LIB)
	for f in $^ ; do \
		sudo install -D -p $$f /usr/local/lib/evohome-exporter/ ; \
	done
	sudo chown daemon /usr/local/lib/evohome-exporter/keys.py
	sudo chmod 400 /usr/local/lib/evohome-exporter/keys.py

install-service: evohome-exporter.service
	sudo install -m 644 -p $^ /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable $^

install-all: install install-service

restart: evohome-exporter.service
	sudo systemctl restart $^
