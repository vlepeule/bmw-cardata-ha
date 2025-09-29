"""Constants for the BMW CarData integration."""

DOMAIN = "cardata"
DEFAULT_SCOPE = "authenticate_user openid cardata:api:read cardata:streaming:read"
DEVICE_CODE_URL = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
TOKEN_URL = "https://customer.bmwgroup.com/gcdm/oauth/token"
API_BASE_URL = "https://api-cardata.bmwgroup.com"
API_VERSION = "v1"
BASIC_DATA_ENDPOINT = "/customers/vehicles/{vin}/basicData"
DEFAULT_STREAM_HOST = "customer.streaming-cardata.bmwgroup.com"
DEFAULT_STREAM_PORT = 9000
DEFAULT_REFRESH_INTERVAL = 45 * 60  # seconds
MQTT_KEEPALIVE = 120
DEBUG_LOG = True
DIAGNOSTIC_LOG_INTERVAL = 60

HV_BATTERY_CONTAINER_NAME = "BimmerData HV Battery"
HV_BATTERY_CONTAINER_PURPOSE = "High voltage battery telemetry"
HV_BATTERY_DESCRIPTORS = [
    # Current high-voltage battery state of charge
    "vehicle.drivetrain.batteryManagement.header",
    "vehicle.drivetrain.electricEngine.charging.acAmpere",
    "vehicle.drivetrain.electricEngine.charging.acVoltage",
    "vehicle.powertrain.electric.battery.preconditioning.automaticMode.statusFeedback",
    "vehicle.vehicle.avgAuxPower",
    "vehicle.powertrain.tractionBattery.charging.port.anyPosition.flap.isOpen",
    "vehicle.powertrain.tractionBattery.charging.port.anyPosition.isPlugged",
    "vehicle.drivetrain.electricEngine.charging.timeToFullyCharged",
    "vehicle.powertrain.electric.battery.charging.acLimit.selected",
    "vehicle.drivetrain.electricEngine.charging.method",
    "vehicle.body.chargingPort.plugEventId",
    "vehicle.drivetrain.electricEngine.charging.phaseNumber",
    "vehicle.trip.segment.end.drivetrain.batteryManagement.hvSoc",
    "vehicle.trip.segment.accumulated.drivetrain.electricEngine.recuperationTotal",
    "vehicle.drivetrain.electricEngine.remainingElectricRange",
    "vehicle.drivetrain.electricEngine.charging.timeRemaining",
    "vehicle.drivetrain.electricEngine.charging.hvStatus",
    "vehicle.drivetrain.electricEngine.charging.lastChargingReason",
    "vehicle.drivetrain.electricEngine.charging.lastChargingResult",
    "vehicle.powertrain.electric.battery.preconditioning.manualMode.statusFeedback",
    "vehicle.drivetrain.electricEngine.charging.reasonChargingEnd",
    "vehicle.powertrain.electric.battery.stateOfCharge.target",
    "vehicle.body.chargingPort.lockedStatus",
    "vehicle.drivetrain.electricEngine.charging.level",
    "vehicle.powertrain.electric.battery.stateOfHealth.displayed",
    "vehicle.vehicleIdentification.basicVehicleData",
    "vehicle.drivetrain.batteryManagement.batterySizeMax"
]

BOOTSTRAP_COMPLETE = "bootstrap_complete"
REQUEST_LOG = "request_log"
REQUEST_LOG_VERSION = 1
REQUEST_LIMIT = 50
REQUEST_WINDOW_SECONDS = 24 * 60 * 60

#fetch_vehicle_mapping returns data like this:
#2025-09-29 18:11:26.340 INFO (MainThread) [custom_components.cardata] Cardata vehicle mappings: [{'mappedSince': '2025-03-27T17:48:41.435Z', 'mappingType': 'PRIMARY', 'vin': 'WBY31AW090FP15359'}, {'mappedSince': '2023-10-10T13:29:38.484Z', 'mappingType': 'PRIMARY', 'vin': 'WBY1Z21020V791850'}]

#telematic reqeusts returns data like this:
#2025-09-29 19:48:19.076 INFO (MainThread) [custom_components.cardata] Cardata telematic data for WBY31AW090FP15359: {'telematicData': {'vehicle.powertrain.electric.battery.preconditioning.manualMode.statusFeedback': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.powertrain.tractionBattery.charging.port.anyPosition.isPlugged': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.powertrain.electric.battery.stateOfHealth.displayed': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.drivetrain.electricEngine.remainingElectricRange': {'timestamp': '2025-09-29T16:48:19.019Z', 'unit': 'km', 'value': '286'}, 'vehicle.powertrain.electric.battery.stateOfCharge.target': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': '%', 'value': '85'}, 'vehicle.trip.segment.end.drivetrain.batteryManagement.hvSoc': {'timestamp': '2025-09-29T12:15:55.055Z', 'unit': '%', 'value': '74'}, 'vehicle.drivetrain.electricEngine.charging.lastChargingResult': {'timestamp': '2025-09-29T16:48:19.019Z', 'unit': None, 'value': 'FAILED'}, 'vehicle.powertrain.electric.battery.charging.acLimit.selected': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': 'A', 'value': '8'}, 'vehicle.drivetrain.electricEngine.charging.phaseNumber': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.drivetrain.batteryManagement.batterySizeMax': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': 'kWh', 'value': '0'}, 'vehicle.drivetrain.electricEngine.charging.method': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': None, 'value': 'NOCHARGING'}, 'vehicle.body.chargingPort.lockedStatus': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': None, 'value': 'CHARGING_CABLE_NOT_LOCKED'}, 'vehicle.powertrain.tractionBattery.charging.port.anyPosition.flap.isOpen': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.vehicle.avgAuxPower': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': 'kW', 'value': '0.5'}, 'vehicle.body.chargingPort.plugEventId': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': None, 'value': '1133'}, 'vehicle.drivetrain.electricEngine.charging.timeToFullyCharged': {'timestamp': None, 'unit': 'min', 'value': None}, 'vehicle.drivetrain.electricEngine.charging.lastChargingReason': {'timestamp': '2025-09-29T16:48:19.019Z', 'unit': None, 'value': 'INVALID'}, 'vehicle.trip.segment.accumulated.drivetrain.electricEngine.recuperationTotal': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.drivetrain.electricEngine.charging.hvStatus': {'timestamp': '2025-09-29T16:48:19.019Z', 'unit': None, 'value': 'NOT_CHARGING'}, 'vehicle.drivetrain.electricEngine.charging.reasonChargingEnd': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.drivetrain.electricEngine.charging.acVoltage': {'timestamp': None, 'unit': 'V', 'value': None}, 'vehicle.drivetrain.electricEngine.charging.acAmpere': {'timestamp': None, 'unit': 'A', 'value': None}, 'vehicle.drivetrain.electricEngine.charging.level': {'timestamp': '2025-09-29T16:48:19.019Z', 'unit': '%', 'value': '74'}, 'vehicle.powertrain.electric.battery.preconditioning.automaticMode.statusFeedback': {'timestamp': None, 'unit': None, 'value': None}, 'vehicle.drivetrain.electricEngine.charging.timeRemaining': {'timestamp': None, 'unit': 'min', 'value': None}, 'vehicle.drivetrain.batteryManagement.header': {'timestamp': '2025-09-29T13:21:16.000Z', 'unit': '%', 'value': '74'}, 'vehicle.vehicleIdentification.basicVehicleData': {'timestamp': None, 'unit': None, 'value': None}}}
