import logging
import os, time, math, requests

URL = "https://gtfsrt.renfe.com/vehicle_positions_LD.json#"
ALERT_DISTANCE = 100
POLL_SECONDS = 15
TIMEOUT = 10

SAMPLE_FILE = "./vehicle_positions_LD.json"


def fetch_raw(): 
    try: 
        resp = requests.get(URL, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(e)
    except ValueError as e:
        print(e)
    return None


data = fetch_raw()
if data:
    print(data["header"])
