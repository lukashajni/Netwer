import os
import queue
from queue import Queue
import time
from datetime import datetime
import requests
import json
from requests import Session
import threading
from threading import Thread
from find_server import *

oneMbps: int = 1000000
uploadByteAmount: int = 100000000

def calculate_speed_in_Mbps(total_bytes: int, elapsed_time: float) -> float:
    return (total_bytes * 8) / (elapsed_time * oneMbps)


"""This function is used to set the best server in the 'best_server.json' file (in order not to find 
    the best server each time a speed test runs"""
def set_best_server(best_server: dict[str, str | int]) -> None:
    try:
        with open("best_server.json", "r") as best_server_fp:
            data = json.load(best_server_fp)
    
        print(f"best server: {data["server"]}")
    # In any other case, clear the file and write the best_server to it
    except:
        with open("best_server.json","w") as best_server_fp:
            json.dump(best_server, best_server_fp, indent=4)
        print("Best server was not found, writing a new best_server to it")

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
def download_speed_test(url: str, speed_time: float) -> dict[str,float | int]:
    megabytes_per_request: int = probe_network(url=url)

    session: Session = requests.Session()
    session.params.update({
        "ckSize": megabytes_per_request
    })
    warmup_test(session=session, url=url)

    start_time: float = time.monotonic()
    total_bytes: int = 0
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

# This function is used as a thread that returns some data to the main upload_speed_test
def upload_worker(worker_queue: "Queue[dict[str,float | int]]", url: str, speed_time: int) -> None:
    session: Session = requests.Session()
    random_data: bytes = os.urandom(uploadByteAmount)
    bytes_received: int = 0
    start_time: float = time.monotonic()    
    
    while time.monotonic() - start_time < speed_time:
        with session.post(url=url, data=random_data) as response:
            print(response.status_code, bytes_received)
            if response.status_code == 200:
                bytes_received += uploadByteAmount
    
    elapsed_time: float = time.monotonic() - start_time
    worker_queue.put({"elapsed_time": elapsed_time, "bytes_received": bytes_received})

# This function starts all workers and gets the average of all of them to calculate the upload speed
def upload_speed_test(url: str, speed_time: int) -> dict[str,float | int]:
    total_bytes: int = 0
    total_elapsed_time: float = 0
    avg_elapsed_time: float = 0 
    worker_amount: int = 5
    
    worker_queue = queue.Queue()
    ul_workers: list[Thread] = []
    for i in range(worker_amount):
        ul_worker: Thread = threading.Thread(target=upload_worker, args=(worker_queue, url, speed_time))
        ul_worker.start()
        ul_workers.append(ul_worker)
    for worker in ul_workers:
        worker.join()
        ul_worker_res =  worker_queue.get()
        total_elapsed_time += ul_worker_res["elapsed_time"]
        total_bytes += ul_worker_res["bytes_received"]
    
    # I need to calculate the average elapsed time, because I can't guarantee that
    # a worker is going to be exactly 15 seconds, so in order to get the most precise
    # measurement I can, I need to get the average of them all
    avg_elapsed_time = total_elapsed_time / worker_amount


    print(f"avg_elapsed_time: {avg_elapsed_time}, total_bytes sent: {total_bytes}" )
    return {"elapsed_time": avg_elapsed_time, "total_bytes": total_bytes}


best_server: dict[str, str | int] = find_best_server(better_scan=False)
set_best_server(best_server)
download_url: str = f"{best_server["server"]}{best_server["dlURL"]}" 
upload_url: str = f"{best_server["server"]}{best_server["ulURL"]}"

test_dict_upload: dict[str,float | int] = upload_speed_test(url=download_url,speed_time=15)
ul_speed_in_Mbps: float = calculate_speed_in_Mbps(test_dict_upload["total_bytes"], test_dict_upload["elapsed_time"])
print(f"Upload speed: {ul_speed_in_Mbps}Mbps")


test_dict: dict[str,float | int] = download_speed_test(url=download_url,speed_time=15)
dl_speed_in_Mbps: float = calculate_speed_in_Mbps(test_dict["total_bytes"], test_dict["elapsed_time"])
print(f"Download speed: {dl_speed_in_Mbps}Mbps")

