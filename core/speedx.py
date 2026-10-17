import os
import queue
from queue import Queue
import time
from datetime import datetime
from tracemalloc import start
import requests
import json
from requests import Session
import threading
from threading import Thread
from pathlib import Path
from core import find_server

oneMbps: int = 1000000
uploadByteAmount: int = 100000000
worker_amount: int = 5


def calculate_speed_in_Mbps(total_bytes: int, elapsed_time: float) -> float:
    return (total_bytes * 8) / (elapsed_time * oneMbps)

def calculate_median(median_arr: list) -> float | int:
    median_arr.sort()
    median_arr_len = len(median_arr)
    if (len(median_arr) % 2 == 0):
        # Take the two numbers in the middle and calculate their average
        return (median_arr[int(median_arr_len / 2)] + median_arr[int(median_arr_len / 2) - 1]) / 2
    # If the length of the median array is an odd number, just return the number in the middle
    return median_arr[int(median_arr_len / 2)] 
"""This function is used to set the best server in the 'best_server.json' file (in order not to find 
    the best server each time a speed test runs"""
def set_best_server(best_server: dict[str, str | int]) -> None:
    best_server_file_path = Path(__file__).resolve().parent / "best_server.json"
    try:
        with open(best_server_file_path, "r") as best_server_fp:
            data = json.load(best_server_fp)
    
        #print(f"best server: {data["server"]}")
    # In any other case, clear the file and write the best_server to it
    except:
        with open(best_server_file_path,"w") as best_server_fp:
            json.dump(best_server, best_server_fp, indent=4)
        #print("Best server was not found, writing a new best_server to it")

# This function is used to warmup a test by its session
def warmup_test(session: Session, url: str) -> None:
    # Do 10 requests for the warmup
    for i in range(10):
        with session.get(url, headers=None, stream=True) as response:
            # print(f"Warmup: {response.status_code}")
            response.raise_for_status()
"""Used for determining how big a request is going to be 
   for the actual upload test"""
def probe_network_ul(url: str) -> int:
    # Maximum bytes a server can receive
    maxRequestSize: int = 1000 * 1000 * 1000 
    currRequestSize: float = 10000
    session: Session = requests.Session()

    while currRequestSize < maxRequestSize:
        random_data: bytes = os.urandom(int(currRequestSize))
        start_time: float = time.monotonic()
        
        try: 
            with session.post(url, data=random_data) as response:
                #print(f"Probing upload: {response.status_code}, currRequestSize: {currRequestSize}")
                response.raise_for_status()
        except requests.exceptions.HTTPError:
            """If the request is too large for the server, set the currRequestSize to the first previous
            request size and break out of the loop"""
            currRequestSize = currRequestSize /2
            break
        elapsed_time: float = time.monotonic() - start_time
        """ If the request is received in less than a second, increase currRequestSize,
        if the currRequestSize is longer than 1 second, exit the loop """
        if elapsed_time <= 1:
            currRequestSize *= 1.2
        else:
            break
    
    """ If someone has an upload speed higher than maxRequestSize, then just
    set currRequestSize to maxRequestSize (because that is the maximum value
    a librespeed server accepts) """
    if currRequestSize > maxRequestSize:
        currRequestSize = maxRequestSize
    #print(f"upload currRequestSize: {currRequestSize}")
    return int(currRequestSize)

"""Used for determining how big a request is going to be 
   for the actual download test"""
def probe_network_dl(url: str) -> int:
    # Maximum megabytes a server can receive
    maxRequestSize: int = 1000 
    currRequestSize: float = 4
    session: Session = requests.Session()

    while currRequestSize < maxRequestSize:
        session.params.update({
            "ckSize": int(currRequestSize)
        })
        start_time: float = time.monotonic()
        total_bytes = 0

        with session.get(url, headers=None, stream=True) as response:
            #print(f"Probing download: {response.status_code}, currRequestSize: {currRequestSize}")
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                total_bytes += len(chunk)

        elapsed_time: float = time.monotonic() - start_time
        #print(f"elapsed_time: {elapsed_time}")
        """ If the request is received in less than a second, increase currRequestSize,
        if the currRequestSize is longer than 1 second, exit the loop """
        if elapsed_time <= 0.5:
            currRequestSize *= 1.2
        else:
            break
    
    """ If someone has a download speed higher than maxRequestSize, then just
    set currRequestSize to maxRequestSize (because that is the maximum value
    a librespeed server accepts) """
    if currRequestSize > maxRequestSize:
        currRequestSize = maxRequestSize
    #print(f"currRequestSize: {currRequestSize}")
    return int(currRequestSize)
def download_worker(worker_queue: "Queue[dict[str,float | int]]", url: str, speed_time: float, megabytes_per_request: int) -> None:
    session: Session = requests.Session()
    session.params.update({
        "ckSize": megabytes_per_request
    })
    warmup_test(session=session, url=url)

    start_time: float = time.monotonic()
    bytes_received: int = 0

    while time.monotonic() - start_time < speed_time:
        with session.get(url, headers=None, stream=True) as response:
            #print(response.status_code, bytes_received)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                """ If request time exceeded the speed test time, then just exit from it
                this is done in order to get the most accurate test as possible """
                if time.monotonic() - start_time > speed_time:
                    break
                bytes_received += len(chunk)
            worker_queue.put({"type":"answer", "megabytes_received": megabytes_per_request })
    elapsed_time: float = time.monotonic() - start_time

    worker_queue.put({"type": "finish","elapsed_time": elapsed_time, "bytes_received": bytes_received})

def download_speed_test(url: str, speed_time: float) -> dict[str,float | int]:
    # I need to probe the the network in order to test how big request the worker can send
    megabytes_per_request: int = probe_network_dl(url=url)

    total_bytes: int = 0
    total_elapsed_time: float = 0
    avg_elapsed_time: float = 0 
    
    worker_queue = queue.Queue()
    dl_workers: list[Thread] = []

    for i in range(worker_amount):
        dl_worker: Thread = threading.Thread(target=download_worker, args=(worker_queue, url, speed_time, megabytes_per_request))
        dl_worker.start()
        dl_workers.append(dl_worker)
    # Used for calculating time for each UI request signal
    requests_time: float = time.monotonic()

    finished_workers: int = 0
    """ This variable is used for tracking how many requests have been successfully sent and is used for
    determining when to send a signal to the UI """
    received_request_amount: int = 0
    # These 2 variables are basically used for calculating the value that the signal will receive
    received_request_bytes_sent: int = 0
    received_request_elapsed_time: int = 0
    while True:
        dl_worker_res =  worker_queue.get()
        match dl_worker_res["type"]:
            case "finish":
                finished_workers += 1
                total_elapsed_time += dl_worker_res["elapsed_time"]
                total_bytes += dl_worker_res["bytes_received"] 
                
                #print(f"total_elapsed_time: {total_elapsed_time}, total_bytes: {total_bytes}")
            case "answer":
                # This is just converted to a format that the UI can understand
                # Convert to bytes
                received_request_bytes_sent += dl_worker_res["megabytes_received"] * 1000000
                received_request_amount += 1
        if received_request_amount == 2:
            """I need to divide the elapsed_time by 2, to be honest I don't know why
            but that gives the closest calculations to the actual result (probably needs changing, but it works for now) """
            mbps_to_send = calculate_speed_in_Mbps(received_request_bytes_sent, time.monotonic() - requests_time) 
            #print(f"mbps to send: {mbps_to_send}, received_request_bytes_sent: {received_request_bytes_sent}")

            yield {"type": "download", "mbps": mbps_to_send } 

            received_request_amount = 0
            received_request_bytes_sent = 0
            requests_time = time.monotonic()
        # I don't know how it could be higher than worker_amount, but I just want to be safe
        if finished_workers >= worker_amount: break

    for worker in dl_workers:
        worker.join()

    # I need to calculate the average elapsed time, because I can't guarantee that
    # a worker is going to be exactly 15 seconds, so in order to get the most precise
    # measurement I can, I need to get the average of them all
    avg_elapsed_time = total_elapsed_time / worker_amount

    #print(f"Recieved {total_bytes} bytes, avg_elapsed_time: {avg_elapsed_time}")
    return {"elapsed_time": avg_elapsed_time, "total_bytes": total_bytes}

# This function is used as a thread that returns some data to the main upload_speed_test
def upload_worker(worker_queue: "Queue[dict[str,float | int]]", url: str, speed_time: int, bytes_per_request: int) -> None:
    session: Session = requests.Session()
    # Make this generate random data every time a request is sent
    random_data: bytes = os.urandom(bytes_per_request)
    bytes_sent: int = 0
    start_time: float = time.monotonic()    
    previous_time: float = start_time

    while time.monotonic() - start_time < speed_time:
        with session.post(url=url, data=random_data) as response:
            #print(response.status_code, bytes_sent)
            if response.status_code == 200:
                bytes_sent += bytes_per_request
                # I basically need to put the all sent bytes becuase the elapsed time is time.monotonic() - start_time 
                worker_queue.put({"type":"answer", "elapsed_time": time.monotonic() - previous_time, "bytes_sent": bytes_per_request })
        previous_time = time.monotonic()

    elapsed_time: float = time.monotonic() - start_time
    worker_queue.put({"type": "finish", "elapsed_time": elapsed_time, "bytes_sent": bytes_sent})

# This function starts all workers and gets the average of all of them to calculate the upload speed
def upload_speed_test(url: str, speed_time: int) -> dict[str,float | int]:
    total_bytes: int = 0
    total_elapsed_time: float = 0
    avg_elapsed_time: float = 0 
    
    worker_queue = queue.Queue()
    ul_workers: list[Thread] = []
    # I need to probe the the network in order to test how big request the worker can send
    bytes_per_request: int = probe_network_ul(url=url)
    for i in range(worker_amount):
        ul_worker: Thread = threading.Thread(target=upload_worker, args=(worker_queue, url, speed_time, bytes_per_request))
        ul_worker.start()
        ul_workers.append(ul_worker)
    
    finished_workers: int = 0
    """ This variable is used for tracking how many requests have been successfully sent and is used for
    determining when to send a signal to the UI """
    sent_request_amount: int = 0
    # These 2 variables are basically used for calculating the value that the singla will receive
    sent_request_bytes_sent: int = 0
    sent_request_elapsed_time: int = 0
    while True:
        ul_worker_res =  worker_queue.get()
        match ul_worker_res["type"]:
            case "finish":
                finished_workers += 1
                total_elapsed_time += ul_worker_res["elapsed_time"]
                total_bytes += ul_worker_res["bytes_sent"]
                
                #print(f"total_elapsed_time: {total_elapsed_time}, total_bytes: {total_bytes}")
            case "answer":
                # This is just converted to a format that the UI can understand
                sent_request_bytes_sent += ul_worker_res["bytes_sent"]
                sent_request_elapsed_time += ul_worker_res["elapsed_time"]
                sent_request_amount += 1
        if sent_request_amount == 2:
            """I need to divide the elapsed_time by worker_amount, to be honest I don't know why
            but that gives the closest calculations to the actual result (probably needs changing, but it works for now) """
            mbps_to_send = calculate_speed_in_Mbps(sent_request_bytes_sent, sent_request_elapsed_time / worker_amount) 
            #print(f"mbps to send: {mbps_to_send}, sent_request_bytes_sent: {sent_request_bytes_sent}\nsent_request_elapsed_time: {sent_request_elapsed_time}")
            yield {"type": "upload", "mbps": mbps_to_send } 

            sent_request_amount = 0
            sent_request_bytes_sent = 0
            sent_request_elapsed_time = 0
        # I don't know how it could be higher than worker_amount, but I just want to be safe
        if finished_workers >= worker_amount: break


    for worker in ul_workers:
        worker.join()
    
    # I need to calculate the average elapsed time, because I can't guarantee that
    # a worker is going to be exactly 15 seconds, so in order to get the most precise
    # measurement I can, I need to get the average of them all
    avg_elapsed_time = total_elapsed_time / worker_amount

    #print(f"avg_elapsed_time: {avg_elapsed_time}, total_bytes sent: {total_bytes}" )
    return {"type": "finish", "elapsed_time": avg_elapsed_time, "total_bytes": total_bytes}

def ping_test(url: str) -> float:
    session: Session = requests.Session()
    warmup_test(session, url)
    
    elapsed_time_array: list(float) = []

    for i in range(10):
        # perf counter should give a more detailed accurate time (in floating point terms)
        start_time: float = time.perf_counter()
        with session.get(url=url, timeout=5) as response:
            response.raise_for_status()
        
        elapsed_time_array.append(time.perf_counter() - start_time)
    
    """ I need to return the median of he elapsed time because that will be
    the most accurate representation possible (probably not, but it will work nonetheless)"""
    return calculate_median(elapsed_time_array) * 1000
    

