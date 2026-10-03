from asyncio import exceptions

import requests
import json
import time

class ServerListFileNotFound(Exception):
    pass

def construct_ping_server(base_url: str, ping_url: str) -> str:
    new_server_url: str = base_url
    # Handle the server url not having the 'https://' at the beginning
    if new_server_url.startswith("//"):
        # Remove the '//' fron new_server_url and add the 'https://'
        new_server_url = new_server_url[2:]
        new_server_url = f"https://{new_server_url}"
    # Handle the server url not having the '/' character at the end
    if not new_server_url.endswith("/"):
        new_server_url += "/"
    
    new_server_url += ping_url
    return new_server_url

def find_server_list():
  try:
    with open("server-list.json", "r") as servers_file:
        data = json.load(servers_file)
        return data
  except:
    raise ServerListFileNotFound("Server list file 'server-list.json' couldn't be found in the same directory as this file")
   
def find_best_download_server():
    server_list = find_server_list()
    best_server = None
    best_elapsed_time: float = 0
 
    for i in range(len(server_list)):
        ping_server_url: str = construct_ping_server(server_list[i]["server"], server_list[i]["pingURL"])
        start_time: float = time.monotonic()
       
        try: 
            total_bytes: int = 0
            with requests.get(url=ping_server_url, headers=None, stream=False, timeout=5) as response:
                print(f"Testing best server: {ping_server_url} , {response.status_code}")
                response.raise_for_status()

            elapsed_time: float = time.monotonic() - start_time
            print(f"elapsed_time: {elapsed_time} total_bytes received: {total_bytes}")
                
            # This needs to be done on the first iteration so that it can actually detect the best server
            if i == 0:
                best_server = server_list[0]
                best_elapsed_time = elapsed_time
            # If the current server has a better (shorter) elapsed time, mark it as a best server
            if elapsed_time < best_elapsed_time:
                best_server = server_list[i]
                best_elapsed_time = elapsed_time
        except requests.exceptions.ConnectionError:
            continue
        except requests.exceptions.HTTPError:
            continue
    print(best_server, best_elapsed_time)

    return best_server

find_best_download_server()

 


   
