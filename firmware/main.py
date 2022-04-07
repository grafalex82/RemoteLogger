import time
import uio as io
import usys as sys
import uasyncio as asyncio
import machine
import network
import webrepl
import uos


class UartMode:
    USB_UART = 0
    LOGGING_UART = 1
    PROGRAMMING_UART = 2


class UartManager:
    UART_CFG = {
        UartMode.USB_UART: {'baudrate': 115200},
        UartMode.LOGGING_UART: {'baudrate': 115200, 'tx': machine.Pin(15), 'rx': machine.Pin(13), 'rxbuf': 2048},
        UartMode.PROGRAMMING_UART: {'baudrate': 38400, 'tx': machine.Pin(15), 'rx': machine.Pin(13), 'rxbuf': 1024, 'timeout': 100}
    }

    def __init__(self):
        self.mutex = asyncio.Lock()
        self.mode = None
        self.uart = self.getUart(UartMode.USB_UART)


    async def acquire(self):
        await self.mutex.acquire()


    def release(self):
        self.mutex.release()


    def getUart(self, mode):
        if self.mode != mode:
            print("Switch to UART mode " + str(mode))
            cfg = UartManager.UART_CFG[mode]
            self.uart = machine.UART(0, **cfg)
            self.mode = mode

        return self.uart


uart_manager = UartManager()


class ScopedUart:
    def __init__(self, mode):
        self.mode = mode

    async def __aenter__(self):
        await uart_manager.acquire()
        return uart_manager.getUart(self.mode)

    async def __aexit__(self, *args):
        uart_manager.release()



class RemoteLogger():
    def __init__(self):
        self.writer = None


    async def connect(self, server, port):
        print("Openning connection to " + server + ":" + str(port)) 
        _, self.writer = await asyncio.open_connection(server, int(port))
        await self.writer.drain()


    async def log(self, msg):
        print(msg)

        self.writer.write((msg+'\n').encode())
        await self.writer.drain()


logger = RemoteLogger()



def halt(err):
    print("Swapping back to USB UART")
    uart = uart_manager.getUart(UartMode.USB_UART)
    uos.dupterm(uart, 1)

    print("Fatal error: " + err)
    for i in range (5, 0, -1):
        print("The app will reboot in {} seconds".format(i))
        time.sleep(1)

    machine.reset()


def coroutine(fn):
    async def coroutineWrapper(*args, **kwargs):
        try:
            await fn(*args, **kwargs)
        except Exception as e:
            buf = io.StringIO()
            sys.print_exception(e, buf)
            halt(buf.getvalue())

    return coroutineWrapper


fastBlinking=True
@coroutine
async def blink():
    led = machine.Pin(2, machine.Pin.OUT, value = 1)

    while True:
        led(not led()) # Fast blinking if no connection
        await asyncio.sleep_ms(1000 if not fastBlinking else 150)

def readConfig():
    print("Reading configuration...") 

    config = {}
    with open("config.txt") as config_file:
        config['ssid'] = config_file.readline().rstrip()
        config['wifi_pw'] = config_file.readline().rstrip()
        config['server'] = config_file.readline().rstrip()
        config['port'] = config_file.readline().rstrip()

    return config


async def connectWiFi(ssid, passwd, timeout=10):
    global fastBlinking

    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    print("Connecting to WiFi: " + ssid)
    sta.connect(ssid, passwd)

    duration = 0
    while not sta.isconnected():
        if duration >= timeout:
            halt("WiFi connection failed. Status=" + str(sta.status()))

        print("Still connecting... Status=" + str(sta.status()))
        duration += 1
        await asyncio.sleep(1)

    print("Connected to WiFi. ifconfig="+str(sta.ifconfig()))
    fastBlinking = False


def swapUART():
    print("Swapping UART to alternate pins. Disconnecting REPL on UART")
    uos.dupterm(None, 1)


@coroutine
async def uart_listener():
    while True:
        async with ScopedUart(UartMode.LOGGING_UART) as uart:
            reader = asyncio.StreamReader(uart)
            data = yield from reader.readline()
            line = data.decode().rstrip()
            await logger.log("UART message: " + line)


async def receiveMsg(stream):
    len = (await stream.read(1))[0]
    data = await stream.read(len)
    return data

async def sendMsg(stream, data):
    stream.write(bytes([len(data)]))
    stream.write(data)
    await stream.drain()

async def xferMsg(src, dst):
    data = await receiveMsg(src)
    await sendMsg(dst, data)


@coroutine
async def firmware_server(tcpreader, tcpwriter):
    await logger.log("Firmware client connected: " + str(tcpreader.get_extra_info('peername')))

    try:
        print("Aquiring UART")
        async with ScopedUart(UartMode.PROGRAMMING_UART) as uart:        
            print("UART aquired")
            uartstream = asyncio.StreamReader(uart)

            while True:
                await asyncio.wait_for(xferMsg(tcpreader, uartstream), timeout=15)
                await asyncio.wait_for(xferMsg(uartstream, tcpwriter), timeout=5)

    except Exception as e:
        await logger.log("Exception: " + repr(e))

    tcpreader.close()
    await tcpreader.wait_closed()
    tcpwriter.close()
    await tcpwriter.wait_closed()
    await logger.log("Firmware client disconnected: " + str(tcpreader.get_extra_info('peername')))


@coroutine
async def main():
    config = readConfig()
    print("Configuration: " + str(config))

    asyncio.create_task(blink())

    await connectWiFi(config['ssid'], config['wifi_pw'])
    await logger.connect(config['server'], config['port'])
    webrepl.start()
    swapUART()
    #asyncio.create_task(uart_listener())

    for i in range(10, 0, -1):
        await logger.log("Starting firmware server in " + str(i) + " seconds")
        await asyncio.sleep(1)
    await asyncio.start_server(firmware_server, "0.0.0.0", 5169)
    #asyncio.create_task(firmware_server())

    i = 0
    while True:
        gc.collect()  # For RAM stats.
        mem_free = gc.mem_free()
        mem_alloc = gc.mem_alloc()

        await logger.log("Memory allocated: " + str(mem_alloc) + " Free memory: " + str(mem_free))
        await asyncio.sleep(5)


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
