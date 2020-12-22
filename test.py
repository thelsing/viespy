import json
import time
import serial
import xml.etree.ElementTree as ET

dummyeventCache = {
  'ecnsysDeviceIdent': b'\x20\xCB\x03\x4F\x00\x00\x01\x3D',
  'K00_KonfiAnlagenschemaV300_V333': '4',
  'K7F_KonfiEinfamilienhaus': '1',
  'K54_Solar_GWG_2010': '4',
  'K2E_KonfiKennungAnschluss':'0',
  'K76_Kommunikationsmodul_GWG':'0',
  'KA0_KonfiKennungFernbedienungA1M1':'0',
  'KA0_KonfiKennungFernbedienungM2':'0',
  'KA0_KonfiKennungFernbedienungM3':'0',
  'K32_GWG_Kennung_AM1':'1',
  'K35_GWG_Kennung_EA1':'0',
  'TemperaturFehler_VLTS_GWG':'0',
  'VSKO_Scot_CES_P80':'0', #GFA_READ,
  'Brennertyp_aktuell':'2',
  'Brennertyp':'2',
  'GWG_Codierstecker_Brennertyp':'2',
  'K76_KonfiKommunikationsmodul':'0',
  'TemperaturFehler_AGTS':'0',
  'K2D_KonfiKennungSTRS1':'0',
  'K8B_KennungKMFeuerungsautomat':'64',
  'K30_KennungIntPumpe':'2',
  'K01_KonfiAnlagentypGWG':'1',
  'K00_KonfiAnlagenschemaGWG_Konstant':'4',
  'K54_Solar':'4',
  'K53_Rangierung':'1',
  'K70_KonfiZpumpeRelaisausgang':'0',
  'HK1_Kennung':'0',
  'HK2_Kennung':'2',
  'HK3_Kennung':'0',
  'KB0_KonfiRaumaufschaltungA1M1':'0',



}

eventTypes = {}
_serial = None
_initialized = False
_lastbytetime = 0
_lastbyte = b''
_connected = False
_port = "/dev/optolink"
_timeout = 5

controlset = {
    'P300': {
        'Baudrate': 4800,
        'Bytesize': 8,          # 'EIGHTBITS'
        'Parity': 'E',          # 'PARITY_EVEN',
        'Stopbits': 2,          # 'STOPBITS_TWO',
        'StartByte': 0x41,
        'Request': 0x00,
        'Response': 0x01,
        'Error': 0x03,
        'Read': 0x01,
        'Write': 0x02,
        'Function_Call': 0x7,
        'Acknowledge': 0x06,
        'Not_initiated': 0x05,
        'Init_Error': 0x15,
        'Reset_Command': 0x04,
        'Reset_Command_Response': 0x05,
        'Sync_Command': 0x160000,
        'Sync_Command_Response': 0x06,
        'Command_bytes_read': 5,
        'Command_bytes_write': 5,
        # init:              send'Reset_Command' receive'Reset_Command_Response' send'Sync_Command'
        # request:           send('StartByte' 'Länge der Nutzdaten als Anzahl der Bytes zwischen diesem Byte und der Prüfsumme' 'Request' 'Read' 'addr' 'checksum')
        # request_response:  receive('Acknowledge' 'StartByte' 'Länge der Nutzdaten als Anzahl der Bytes zwischen diesem Byte und der Prüfsumme' 'Response' 'Read' 'addr' 'Anzahl der Bytes des Wertes' 'Wert' 'checksum')
    },
    'KW': {
        'StartByte': 0x01,
        'Read': 0xF7,
        'Write': 0xF4,
        'Acknowledge': 0x05,
    },

}
_controlset = controlset["P300"]

def parseEventTypes(filename):
    tree = ET.parse(filename)
    root = tree.getroot()
    for element in root.findall(".//EventType"):
        id = element.find("ID").text
        id = id.split('~')[0]
        address = element.find("Address")
        eventtype = { "id":id}
        if address is None:
            eventTypes[id] = eventtype
            continue
        if address.text is not None:
            eventtype["addr"] = address.text[2:]
        
        blockLen = element.find("BlockLength")
        eventtype["blockLen"] = int(blockLen.text)

        bytepos = element.find("BytePosition")
        eventtype["bytePos"] = int(bytepos.text)

        bytelen = element.find("ByteLength")
        eventtype["byteLen"] = int(bytelen.text)

        datatype = element.find("SDKDataType")
        if datatype is not None:
            eventtype["datatype"] = datatype.text

    
        eventTypes[id] = eventtype
        # Eventtypen für Schaltzeiten hinzufügen
        if not id.startswith("Schaltzeiten"): continue

        for day in ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']:
            for suffix in ['00', '01', '02', '03', '04', '05', '06', '07', '08']:
                eventTypes[id + '_' + day + '_' + suffix] = { "to": "do"}


def getDeviceId(deviceIdent, identF0 = None):
    ident = deviceIdent[0:2].hex().upper()
    #hwRead = deviceIdent[2:3].hex().upper() seems to be irrelevant 

    #f0 is a short in the xml so convert the two bytes to short. endianess is hopefully right
    f0 = None
    if identF0 is not None:
        f0 = int.from_bytes(identF0, "big") 

    swRead = deviceIdent[3:4].hex().upper()
    idBase = None
    id = None
    tree = ET.parse("ecnDataPointType.xml")
    root = tree.getroot()
    for element in root.findall(".//DataPointType"):
        identification = element.find("Identification")
        
        if identification is None or identification.text != ident: continue

        identificationExt = element.find("IdentificationExtension")
        if identificationExt is None: 
            idBase = element.find("ID").text
            continue

        if len(identificationExt.text) != 4: continue

        sw = identificationExt.text[2:4]
        if swRead < sw : continue
        
        identificationExtTill = element.find("IdentificationExtensionTill")

        if identificationExtTill is None or len(identificationExtTill.text) != 4: continue

        swTill = identificationExtTill.text[2:4]
        if swRead > swTill : continue

        #if identificationExt is not None: print("ext: " +identificationExt.text) 
        #if identificationExtTill is not None: print("till: " + identificationExtTill.text)

        if identF0 is None:
            if id is not None: return None #we have more than one possible device. retry with f0ident

            id = element.find("ID").text
        else:
            f0from = element.find("F0")
            f0till = element.find("F0Till")
            if f0from is None or f0till is None: continue 
            f0fromVal = int(f0from.text)
            f0tillVal = int(f0till.text)

            if f0 < f0fromVal or f0 > f0tillVal: continue
            if id is not None: return None #we have more than one possible device. this should not happen

            id = element.find("ID").text

    if id is None: return idBase 
    return id

def indentifyDevice():
    deviceIdent = readEventType('ecnsysDeviceIdent')
    deviceId = getDeviceId(deviceIdent)
    if deviceId is None:
        f0ident = readEventType('ecnsysDeviceIdentF0')
        deviceId = getDeviceId(deviceId, f0ident)

    if deviceId is None:
        raise Exception('no device found')

    return deviceId

def validateCondition(condition, eventCache):
    type = condition.attrib["Type"]
    
    condEventTyp = condition.find("EventTypeID").text
    condValue = condition.find("Value").text
    if condEventTyp not in eventCache: eventCache[condEventTyp] = readEventType(condEventTyp)
    
    if condValue == str(eventCache[condEventTyp]) and type == "Equal":
        return True
    return False

def validateConditionGroup(conditionGroup, eventCache):
    type = conditionGroup.attrib["Type"]
    result = type == "And"

    for condition in conditionGroup.findall("./DisplayConditions/DisplayCondition"):
        if result == validateCondition(condition, eventCache): # "Or"+ False/"And" + True
            continue
        return not result

    for conditionGroup in conditionGroup.findall("./DisplayConditionGroups/DisplayConditionGroup"):
        if result == validateConditionGroup(conditionGroup, eventCache): # "Or"+ False/"And" + True
            continue
        return not result
    return result

def validateElement(element, eventCache):
    hasNoConditions = True
    valid = False
    for conditionGroup in element.findall("./DisplayConditionGroups/DisplayConditionGroup"):
        hasNoConditions = False
        valid = validateConditionGroup(conditionGroup, eventCache)
        if valid: break

    return hasNoConditions or valid

def handleEventTypeGroup(deviceId, eventCache, element):
    datapoint = element.find("DataPointTypeID")
    if not datapoint.text.startswith(deviceId):
        return None

    group = {
        "id": element.find("ID").text,
        "name" : element.find("Name").text,
    }

    if not validateElement(element, eventCache): return None

    for eventtype in element.findall("EventTypes/EventType"):
        if not validateElement(eventtype, eventCache): continue
        
        if not "eventtypes" in group: group["eventtypes"] = []
        eventTypeId = eventtype.find("EventTypeID").text

        group["eventtypes"].append(eventTypes[eventTypeId])

    for child in element.findall("./EventTypeGroups/EventTypeGroup"):
        if not "children" in group: group["children"] = {}

        id = child.find("ID").text
        childGroup = handleEventTypeGroup(deviceId, eventCache, child)

        if childGroup is None: continue

        group["children"][id] = childGroup
    return group

def _bytes2hexstring(bytesvalue):
    '''
    Create hex-formatted string from bytearray
    :param bytesvalue: Bytes to convert
    :type bytesvalue: bytearray
    :return: Converted hex string
    :rtype: str
    '''
    return "".join("{:02x}".format(c) for c in bytesvalue)

def _calc_checksum(packet):
    '''
    Calculate checksum for P300 protocol packets
    :parameter packet: Data packet for which to calculate checksum
    :type packet: bytearray
    :return: Calculated checksum
    :rtype: int
    '''
    checksum = 0
    if len(packet) > 0:
        if packet[:1] == b'\x41':
            packet = packet[1:]
            checksum = sum(packet)
            checksum = checksum - int(checksum / 256) * 256
        else:
            print('bytes to calculate checksum from not starting with start byte')
    else:
        print('No bytes received to calculate checksum')
    return checksum

def _connect():
    global _connected
    global _serial
    if _connected and _serial:
        return True

    _serial = serial.Serial()
    _serial.baudrate = _controlset['Baudrate']
    _serial.parity = _controlset['Parity']
    _serial.bytesize = _controlset['Bytesize']
    _serial.stopbits = _controlset['Stopbits']
    _serial.port = _port
    _serial.timeout = 1
    _serial.open()

    print('Connected to {}'.format(_port))
    _connected = True
    return True

def _int2bytes(value, length, signed=False):
    '''
    Convert value to bytearray with respect to defined length and sign format.
    Value exceeding limit set by length and sign will be truncated
    :parameter value: Value to convert
    :type value: int
    :parameter length: number of bytes to create
    :type length: int
    :parameter signed: True if result should be a signed int, False for unsigned
    :type signed: bool
    :return: Converted value
    :rtype: bytearray
    '''
    value = value % (2 ** (length * 8))
    return value.to_bytes(length, byteorder='big', signed=signed)

def _send_bytes(packet):
    '''
    Send data to device
    :param packet: Data to be sent
    :type packet: bytearray
    :return: Returns False, if no connection is established or write failed; True otherwise
    :rtype: bool
    '''
    global _connected
    global _serial
    if not _connected:
        return False
    try:
        _serial.write(packet)
    except serial.SerialTimeoutException:
        return False
    # self.logger.debug('send_bytes: Sent {}'.format(packet))
    return True

def _read_bytes(length):
    '''
    Try to read bytes from device
    :param length: Number of bytes to read
    :type length: int
    :return: Number of bytes actually read
    :rtype: int
    '''
    global _connected
    global _lastbyte
    global _initialized
    global _lastbytetime
    if not _connected:
        return 0
    totalreadbytes = bytes()
    # self.logger.debug('read_bytes: Start read')
    starttime = time.time()
    # don't wait for input indefinitely, stop after self._timeout seconds
    while time.time() <= starttime + _timeout:
        readbyte = _serial.read()
        _lastbyte = readbyte
        # self.logger.debug('read_bytes: Read {}'.format(readbyte))
        if readbyte != b'':
            _lastbytetime = time.time()
        else:
            return totalreadbytes
        totalreadbytes += readbyte
        if len(totalreadbytes) >= length:
            return totalreadbytes
    # timeout reached, did we read anything?
    if not totalreadbytes:
        # just in case, force plugin to reconnect
        _connected = False
        _initialized = False
    # return what we got so far, might be 0
    return totalreadbytes

def _init_communication():
    '''
    After connecting to the device, setup the communication protocol
    :return: Returns True, if communication was established successfully, False otherwise
    :rtype: bool
    '''
    global _initialized
    global _lastbyte
    # just try to connect anyway; if connected, this does nothing and no harm, if not, it connects
    if not _connect():
        print('Init communication not possible as connect failed.')
        return False
    # if device answers SYNC b'\x16\x00\x00' with b'\x06', comm is initialized
    print('Init Communication....')
    is_initialized = False
    initstringsent = False
    print('send_bytes: Send reset command {}'.format(_int2bytes(_controlset['Reset_Command'], 1)))
    _send_bytes(_int2bytes(_controlset['Reset_Command'], 1))
    readbyte = _read_bytes(1)
    print('read_bytes: read {}, last byte is {}'.format(readbyte, _lastbyte))
    for i in range(0, 10):
        if initstringsent and _lastbyte == _int2bytes(_controlset['Acknowledge'], 1):
            # Schnittstelle hat auf den Initialisierungsstring mit OK geantwortet. Die Abfrage von Werten kann beginnen. Diese Funktion meldet hierzu True zurück.
            is_initialized = True
            print('Device acknowledged initialization')
            break
        if _lastbyte == _int2bytes(_controlset['Not_initiated'], 1):
            # Schnittstelle ist zurückgesetzt und wartet auf Daten; Antwort b'\x05' = Warten auf Initialisierungsstring oder Antwort b'\x06' = Schnittstelle initialisiert
            _send_bytes(_int2bytes(_controlset['Sync_Command'], 3))
            print('send_bytes: Send sync command {}'.format(_int2bytes(_controlset['Sync_Command'], 3)))
            initstringsent = True
        elif _lastbyte == _int2bytes(_controlset['Init_Error'], 1):
            print('The interface has reported an error (\x15), loop increment {}'.format(i))
            _send_bytes(_int2bytes(_controlset['Reset_Command'], 1))
            print('send_bytes: Send reset command {}'.format(_int2bytes(_controlset['Reset_Command'], 1)))
            initstringsent = False
        else:
            _send_bytes(_int2bytes(_controlset['Reset_Command'], 1))
            print('send_bytes: Send reset command {}'.format(_int2bytes(_controlset['Reset_Command'], 1)))
            initstringsent = False
        readbyte = _read_bytes(1)
        print('read_bytes: read {}, last byte is {}'.format(readbyte, _lastbyte))
    print('Communication initialized: {}'.format(is_initialized))
    _initialized = is_initialized
    return is_initialized

def _parse_response(response, eventtype):
    '''
    Process device response data, try to parse type and value and assign value to associated item
    :param response: Data received from device
    :type response: bytearray
    '''

    # A read_response telegram looks like this: ACK (1 byte), startbyte (1 byte), data length in bytes (1 byte), request/response (1 byte), read/write (1 byte), addr (2 byte), amount of valuebytes (1 byte), value (bytes as per last byte), checksum (1 byte)
    # A write_response telegram looks like this: ACK (1 byte), startbyte (1 byte), data length in bytes (1 byte), request/response (1 byte), read/write (1 byte), addr (2 byte), amount of bytes written (1 byte), checksum (1 byte)

    # Validate checksum
    checksum = _calc_checksum(response[1:len(response) - 1])  # first, cut first byte (ACK) and last byte (checksum) and then calculate checksum
    received_checksum = response[len(response) - 1]
    if received_checksum != checksum:
        print('Calculated checksum {} does not match received checksum of {}! Ignoring reponse.'.format(checksum, received_checksum))
        return

    # Extract command/address, valuebytes and valuebytecount out of response
    commandcode = response[5:7].hex()
    responsetypecode = response[3]  # 0x00 = Anfrage, 0x01 = Antwort, 0x03 = Fehler
    responsedatacode = response[4]  # 0x01 = ReadData, 0x02 = WriteData, 0x07 = Function Call
    valuebytecount = response[7]
    print('Response decoded to: commandcode: {}, responsedatacode: {}, valuebytecount: {}'.format(commandcode, responsedatacode, valuebytecount))

    # Extract databytes out of response
    rawdatabytes = bytearray()
    rawdatabytes.extend(response[8:8 + (valuebytecount)])
    print('Rawdatabytes formatted: {} and unformatted: {}'.format(_bytes2hexstring(rawdatabytes), rawdatabytes))

    # Process response for items if read response and not error
    if responsedatacode != 1 or responsetypecode == 3:
        return b''

    # Process response for items in item-dict using the commandcode
    bpos = eventtype["bytePos"]
    blen = eventtype["byteLen"]
    datatype = eventtype["datatype"]
    rawdatabytes = rawdatabytes[bpos:bpos+blen]
    
    if datatype == "ByteArray":
        return rawdatabytes
    if datatype == "Int":
        return int(rawdatabytes[0])
    return rawdatabytes

def _send_command(packet, packetlen_response, eventtype):
    '''
    Send command sequence to device
    :param packet: Command sequence to send
    :type packet: bytearray
    :param packetlen_response: number of bytes expected in reply
    :type packetlen_response: int
    '''
    global _initialized
    if not _initialized or (time.time() - 500) > _lastbytetime:
        if _initialized:
            print('Communication timed out, trying to reestablish communication.')
        else:
            print('Communication no longer initialized, trying to reestablish.')
        _init_communication()
    if _initialized:
        # send query

        _send_bytes(packet)
        print('Successfully sent packet: {}'.format(_bytes2hexstring(packet)))
        time.sleep(0.1)

        # receive response
        response_packet = bytearray()
        
        print('Trying to receive {} bytes of the response.'.format(packetlen_response))
        chunk = _read_bytes(packetlen_response)
        time.sleep(0.1)
        print('Received {} bytes chunk of response as hexstring {} and as bytes {}'.format(len(chunk), _bytes2hexstring(chunk), chunk))
        if len(chunk) != 0:
            if chunk[:1] == _int2bytes(_controlset['Error'], 1):
                print('Interface returned error! response was: {}'.format(chunk))
            elif len(chunk) == 1 and chunk[:1] == _int2bytes(_controlset['Not_initiated'], 1):
                print('Received invalid chunk, connection not initialized. Forcing re-initialize...')
                _initialized = False
            elif chunk[:1] != _int2bytes(_controlset['Acknowledge'], 1):
                print('Received invalid chunk, not starting with ACK! response was: {}'.format(chunk))
            else:
                # self.logger.info('Received chunk! response was: {}, Hand over to parse_response now.format(chunk))
                response_packet.extend(chunk)
                return _parse_response(response_packet, eventtype)
        else:
            print('Received 0 bytes chunk - ignoring response_packet! chunk was: {}'.format(chunk))




def send_read_command(commandname):
    '''
    Create formatted command sequence from command name and send to device
    :param commandname: Command for which to create command sequence as defined in "commands.py"
    :type commandname: str
    '''

    # A read_request telegram looks like this: ACK (1 byte), startbyte (1 byte), data length in bytes (1 byte), request/response (1 byte), read/write (1 byte), addr (2 byte), amount of value bytes expected in answer (1 byte), checksum (1 byte)
    print('Got a new read job: Command {}'.format(commandname))

    # Get command config
    commandconf = eventTypes[commandname]
    print('Command config: {}'.format(commandconf))
    commandcode = (commandconf['addr']).lower()
    commandvaluebytes = commandconf['blockLen']

    # Build packet for read commands
    packet = bytearray()
    packet.extend(_int2bytes(_controlset['StartByte'], 1))
    packet.extend(_int2bytes(_controlset['Command_bytes_read'], 1))
    packet.extend(_int2bytes(_controlset['Request'], 1))
    packet.extend(_int2bytes(_controlset['Read'], 1))
    packet.extend(bytes.fromhex(commandcode))
    packet.extend(_int2bytes(commandvaluebytes, 1))
    packet.extend(_int2bytes(_calc_checksum(packet), 1))
    print('Preparing command {} with packet to be sent as hexstring: {} and as bytes: {}'.format(commandname, _bytes2hexstring(packet), packet))
    packetlen_response = int(_controlset['Command_bytes_read']) + 4 + int(commandvaluebytes)

    # hand over built packet to send_command
    return _send_command(packet, packetlen_response, commandconf) 

def readEventType(eventTypeId):
    #return dummyeventCache[eventTypeId]
    return send_read_command(eventTypeId)


parseEventTypes("ecnEventType.xml")
parseEventTypes("sysEventType.xml")
parseEventTypes("sysDeviceIdent.xml")
parseEventTypes("sysDeviceIdentExt.xml")

deviceId = indentifyDevice()

print(deviceId)

tree = ET.parse("ecnEventTypeGroup.xml")
root = tree.getroot()

eventCache = {}
groups = {}

for element in root.findall("EventTypeGroup"):
    
    id = element.find("ID").text
    group = handleEventTypeGroup(deviceId, eventCache, element)

    if group is None: continue

    groups[id] = group

    

print(json.dumps(groups, indent=4))






#with open('ecnEventType.xml') as fd:
#    eventTypes = xmltodict.parse(fd.read())

#with open('ecnDataPointType.xml') as fd:
#    dataPointTypes = xmltodict.parse(fd.read())

#with open('ecnDataPointType.xml') as fd:
#    eventTypeGroups = xmltodict.parse(fd.read())

#with open('Textresource_de.xml') as fd:
#    texts = xmltodict.parse(fd.read())

#print(json.dumps(eventTypes, indent=4))

