import time
import requests
from requests import Session
from find_server import *

oneMbps: int = 1000000

# This function is used to warmup a test by its session
def warmup_test(session: Session, url: str) -> None:
    # Do 10 requests for the warmup
    for i in range(10):
        with session.get(url, headers=None, stream=True) as response:
            # print(f"Warmup: {response.status_code}")
            response.raise_for_status()

def probe_network(url: str) -> int:
    # Maximum megabytes a server can receive
    maxRequestSize: int = 1024 
    currRequestSize: int = 4
    session: Session = requests.Session()

    while currRequestSize < maxRequestSize:
        session.params.update({
            "ckSize": currRequestSize
        })
        start_time: float = time.monotonic()
        total_bytes = 0

        with session.get(url, headers=None, stream=True) as response:
            print(f"Probing: {response.status_code}, currRequestSize: {currRequestSize}")
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                total_bytes += len(chunk)

        elapsed_time: float = time.monotonic() - start_time
        #print(f"elapsed_time: {elapsed_time}")
        """ If the request is received in less than a second, increase currRequestSize,
        if the currRequestSize is longer than 1 second, exit the loop """
        if elapsed_time <= 1:
            currRequestSize *= 4
        else:
            break
    
    """ If someone has a download speed higher than maxRequestSize, then just
    set currRequestSize to maxRequestSize (because that is the maximum value
    a librespeed server accepts) """
    if currRequestSize > maxRequestSize:
        currRequestSize = maxRequestSize
    #print(f"currRequestSize: {currRequestSize}")
    return currRequestSize
def download_speed_test(url: str, speed_time: float) -> dict[str,float]:
    megabytes_per_request: int = probe_network(url=url)

    session: Session = requests.Session()
    session.params.update({
        "ckSize": megabytes_per_request
    })
    warmup_test(session=session, url=url)

    start_time: float = time.monotonic()
    total_bytes = 0
    while time.monotonic() - start_time < speed_time:
        with session.get(url, headers=None, stream=True) as response:
            print(response.status_code)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                """ If request time exceeded the speed test time, then just exit from it
                this is done in order to get the most accurate test as possible """
                if time.monotonic() - start_time > speed_time:
                    break
                total_bytes += len(chunk)

    elapsed_time: float = time.monotonic() - start_time
    print(f"Recieved {total_bytes} bytes, elapsed_time: {elapsed_time}")
    return {"elapsed_time": elapsed_time, "total_bytes": total_bytes}

best_server: dict[str, str | int] = find_best_server(better_scan=False)
download_url: str = f"{best_server["server"]}{best_server["dlURL"]}" 

test_dict: dict[str,float] = download_speed_test(url=download_url,speed_time=15)
speed_in_Mbps: float = (test_dict["total_bytes"] * 8) / (test_dict["elapsed_time"] * oneMbps)
print(f"Download speed: {speed_in_Mbps}Mbps")

