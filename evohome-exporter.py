#!/usr/bin/python3

import sys
import time
from evohomeclient2 import EvohomeClient
from keys import username, password
import prometheus_client as prom

timeout=60

def refreshEvohome(myclient):
  try:
    myclient._login()
  except Exception as e:
    print('{}: {}'.format(type(e).__name__, str(e)), file=sys.stderr)
    return False
  return time.time()

if __name__ == '__main__':
  eht = prom.Gauge('evohome_temperature_celcius', 'Evohome temperatuur in celsius', ['name', 'thermostat', 'id', 'type'])
  upd = prom.Gauge('evohome_updated'            , 'Evohome client last updated')
  up  = prom.Gauge('evohome_up'                 , 'Evohome client status')
  prom.start_http_server(8082)
  client = EvohomeClient(username, password)
  updated = time.time()

  while True:
    if updated:
      up.set(1)
      upd.set(updated)
      for d in client.temperatures():
        eht.labels(d['name'],d['thermostat'],d['id'],'measured').set(d['temp'])
        eht.labels(d['name'],d['thermostat'],d['id'],'setpoint').set(d['setpoint'])
    else:
      up.set(0)
    time.sleep(timeout)
    updated = refreshEvohome(client)
