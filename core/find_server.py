import requests
import json
import time

class ServerListFileNotFound(Exception):
    pass

def check_best_server_file() -> dict[str, str | int]:
    try:
        with open("best_server.json", "r") as best_server_fp:
            data = json.load(best_server_fp)
        return data
    except:
        # If there is no best server found, return and id of -1 which indicates that there is no best server yet
        return {"id": -1}

def construct_ping_server(server_dict: dict[str,str | int], base_url: str, ping_url: str) -> str:
    new_server_url: str = base_url
    # Handle the server url not having the 'https://' at the beginning
    if new_server_url.startswith("//"):
        # Remove the '//' fron new_server_url and add the 'https://'
        new_server_url = new_server_url[2:]
        new_server_url = f"https://{new_server_url}"
    # Handle the server url not having the '/' character at the end
    if not new_server_url.endswith("/"):
        new_server_url += "/"
    server_dict["server"] = new_server_url

    new_server_url += ping_url
    return new_server_url

def find_server_list():
  try:
    with open("server-list.json", "r") as servers_file:
        data = json.load(servers_file)
        return data
  except:
    raise ServerListFileNotFound("Server list file 'server-list.json' couldn't be found in the same directory as this file")
   
def find_best_server(better_scan: bool) -> dict[str, str | int]:
    best_server_from_file: dict[str, str | int] = check_best_server_file()
    if int(best_server_from_file["id"]) >= 0:
        return best_server_from_file

    server_list = find_server_list()
    best_server: dict[str, str | int] = dict()
    best_elapsed_time: float = 0
 
    for i in range(len(server_list)):
        ping_server_url: str = construct_ping_server(server_list[i],server_list[i]["server"], server_list[i]["pingURL"])
        start_time: float = time.monotonic()
       
        try: 
            iterations: int = 1
            if better_scan:
                iterations = 5
            total_elapsed_time: float = 0
            # Used for marking a server timed out
            server_timed_out: bool = False
            # In case a better scan is needed, multiple requests are sent to each server 
            for j in range(iterations):
                try:
                    with requests.get(url=ping_server_url, headers=None, stream=False, timeout=5) as response:
                        print(f"Testing best server: {ping_server_url} , {response.status_code} ", end=" ")
                        response.raise_for_status()

                    elapsed_time: float = time.monotonic() - start_time
                    print(f"elapsed_time: {elapsed_time}")
                    total_elapsed_time += elapsed_time
                except requests.exceptions.Timeout:
                    server_timed_out = True
                    print("Server timed out")
                    break
                                    
                # This needs to be done on the first iteration so that it can actually detect the best server
            if i == 0:
                best_server = server_list[0]
                best_elapsed_time = total_elapsed_time
            # If the server timed out, don't check if it has the best total_elapsed_time
            if server_timed_out:
                break
            # If the current server has a better (shorter) elapsed time, mark it as a best server
            if total_elapsed_time < best_elapsed_time:
                best_server = server_list[i]
                best_elapsed_time = total_elapsed_time
            print(f"total_elapsed_time: {total_elapsed_time}")
        except requests.exceptions.ConnectionError:
            continue
        except requests.exceptions.HTTPError:
            continue
    print(best_server, best_elapsed_time)

    return best_server

   
