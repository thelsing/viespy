import xmltodict
import json
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

def readEventType(eventTypeId):
    return dummyeventCache[eventTypeId]

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
        eventtype["address"] = address.text
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
    
    if condValue == eventCache[condEventTyp] and type == "Equal":
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

