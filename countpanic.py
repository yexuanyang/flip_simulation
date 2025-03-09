import json
import socket
import pexpect
import time
import threading

class SocketClient:
    def __init__(self, server_address, need_revert=False, telnethost=None, telnetport=None, snapname=None):
        """
        :param server_address: socket file path
        :param need_revert: default is False, Is it necessary to use monitor to return to snapshot after qemu crashes? set True if it is
        :param telnethost: default is NoneIf need_revert is True, set it to the monitor's IP address
        :param telnetport: default is NoneIf need_revert is True, set it to the monitor's telnet port
        :param snapname:  default is NoneIf need_revert is True, set it to the snapname reverted to after qemu paniced"""
        # panic count number
        self.panic = 0
        # unix domain sockets 
        self.server_address = server_address
        socket_family = socket.AF_UNIX
        socket_type = socket.SOCK_STREAM
        
        self.need_revert = need_revert

        self.sock = socket.socket(socket_family, socket_type)
        try:
            self.sock.connect(self.server_address)
            print("socket connection established.")
        except Exception as e:
            raise e

        if need_revert:
            # create a telnet client connected to monitor save and load snapshot
            self.monitor = TelnetClient(telnethost, telnetport)
            self.monitor.connect()
            # create a snapshot to revert to after qemu crashes
            self.snapname = snapname
            self.monitor.send_command(f"savevm {snapname}")

    def send(self, data: str):
        """Send str to socket server"""
        self.sock.sendall(data.encode())
    
    def listen(self):
        """Listen the socket server and get the response, check if guest is paniced."""
        buffer = ""
        print("socket connection start listening...")
        while True:
            data = self.sock.recv(1024)
            if not data:
                # qemu shutdown
                break
            buffer += data.decode()
            # parse the response data to json objects
            results, buffer = parse_json_objects(buffer)
            # iterate all objects
            for res in results:
                print(res)
                if res.get("event", "") == "GUEST_PANICKED":
                    self.panic += 1
                    if self.need_revert:
                        # revert to the snapshot.
                        self.monitor.send_command("loadvm " + self.snapname)
    
    def __del__(self):
        """Clean the socket and monitor. 
        Note: It need_revert is True, monitor will create a tmporary snapshot and the tmporary snapshot can not be deleted, 
        because when the qemu shutdown, monitor will quit as well"""
        if self.need_revert:
            self.monitor.disconnect()
        self.sock.close()

class TelnetClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connection = None

    def connect(self):
        """Connect to the telnet server"""
        self.connection = pexpect.spawn(f"telnet {self.host} {self.port}")
        self.connection.expect("\(qemu\) ")
        print("telnet connection established.")

    def send_command(self, command):
        """Send a command to the telnet server"""
        if self.connection:
            self.connection.sendline(command)
            self.connection.expect("\(qemu\) ")
            return self.connection.before.decode()
        else:
            raise ConnectionError("Not connected to the server")

    def disconnect(self):
        """Disconnect from the telnet server"""
        if self.connection:
            self.connection.sendline("\x1d")
            self.connection.expect("telnet> ")
            self.connection.sendline("quit")
            self.connection.close()
            self.connection = None
            print("telnet connection closed.")
        else:
            raise ConnectionError("Not connected to the server")
        

class SshClient:
    def __init__(self, hostname, port, username, password):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.connection = None

    def connect(self):
        """Connect to the SSH server"""
        while True:
            try:
                self.connection = pexpect.spawn(f'ssh {self.username}@{self.hostname} -p {self.port}')
                self.connection.expect('password:')
                self.connection.sendline(self.password)
                self.connection.expect(f'{self.username}@')
                print("SSH connection established.")
                break
            except pexpect.exceptions.TIMEOUT:
                print("SSH connection failed: Timeout, retrying in 5 seconds...")
                time.sleep(5)
            except pexpect.exceptions.EOF:
                print("SSH connection failed: Unexpected EOF, retrying in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                print(f"SSH connection failed: {e}, retrying in 5 seconds...")
                time.sleep(5)

    def disconnect(self):
        """Disconnect from the SSH server"""
        if self.connection:
            self.connection.sendline('exit')
            self.connection.close()
            self.connection = None
            print("SSH connection closed.")
    
    def check_ssh(self):
        """Check the ssh is usable"""
        print("Checking SSH service for the object machine")
        self.connect()
        self.disconnect()
        print("SSH is usable now.")


def parse_json_objects(buffer):
    results = []
    while buffer:
        try:
            obj, idx = json.JSONDecoder().raw_decode(buffer)
            results.append(obj)
            buffer = buffer[idx:].lstrip()  # remove parsed part
        except json.JSONDecodeError:
            # incomplete json object, parse it the next time
            break
    return results, buffer

def count_panic(sockfile):
    print("start listening...")
    socketc = SocketClient(sockfile)
    socketc.send('{"execute": "qmp_capabilities"}')
    socketc.listen()
    print("panic count: " + str(socketc.panic))

if __name__=="__main__":
    ssh_client = SshClient("localhost", 2222, "root", "519ailab")
    ssh_client.check_ssh()
    # Qemu is already booted now.
    socketc = SocketClient("/tmp/qmp.sock")
    socketc.send('{"execute": "qmp_capabilities"}')
    socketc.listen()
    print("panic count: " + str(socketc.panic))