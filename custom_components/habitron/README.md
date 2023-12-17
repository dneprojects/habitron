<h2 align="center">
  <a href="https://habitron.de"><img src="./logos/logo@2x.png" alt="Habitron logotype" width="300"></a>
  <br>
  <i>Home Assistant Habitron custom integration</i>
  <br>
</h2>

<p align="center">
  <a href="https://github.com/custom-components/hacs"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg"></a>
  <img src="https://img.shields.io/github/v/release/dneprojects/habitron" alt="Current version">
</p>

The `habitron` implementation allows you to integrate your [Habitron](https://www.habitron.de/) devices in Home Assistant. It is implemented using a _polling_ model in _async_.

## Configuration

For the habitron integration to work, the network interface SmartIP must be reachable via your local network. During configuration, the DNS hostname or the IP address has to given.
A second parameter is used to control the polling update interval.

| Configuration parameter     | Optional  | Description  |
| :-------------------------- | :-------- | :----------- |
| `Host name or IP of SmartIP`| no        | Either the DNS host name of the SmartIP or its IP address.
| `Update interval [s]`       | no        | Polling update interval in seconds, must be between 2 and 10 seconds.
| `Perform cyclic updates`    | no        | Must be checked for nomal operation. Uncheck only to suspend polling for communication with SmartConfig software.

These parameters can be changed after installation as well.

## Entities

For any module, a device is created. These will show up after the discovery phase and can be associated with Home Assistant rooms or zones.
According to the modules found, several entities will be created automatically.

### Lights

This integration creates light entities for all module outputs, and dimmers. If covers are configured, the associated outputs will not appear as lights. All outputs without names are deactivated.

### LEDs

The red LEDs around the buttons on Smart Controller are implemented as switches as they should not appear as lights. Even if no nae is given, all LEDs will show up as entities.

### Covers

If output pairs are used to drive a cover, a cover entitiy is cerated. The output polarity (which one of the pair is used to open, which one to close) is configured automatically. If tilt times have been stored in the module, the cover has an additional tilt property.

### Binary Sensors

For all module inputs, binary sensors are created. The integration detects wether an input is configured as push button or as a switch. The only distinction between these categories is a different icon.

In addition, habitron flags (Merker) are represented as binary sensors. These flags reflect global or module internal states.

For modules, which support motion detection, binary sensors are created, too.

### Sensors

Depending on the module, a couple of sensors are created:

| Sensor               | Description |
| :------------------- | :------------------------------------------------------------ |
| Temperature          | Temperatures of ambient air, power electronics, ext. sensor.  |
| Humidity             | Air humidity in percent.                                      |
| Luminance            | Luminace in lux.                                              |
| Air qualitiy         | Index in percent.                                             |
| Motion               | Motion sensors appear as binary sensors (see above)           |

### Buttons

The habitron integration creates buttons for collective commands, direct commands, and visualization commands.

### Numbers

For Smart Controller modules, an input number entitiy is created to control the two temperature setpoints.

### Select

The habitron system offers modes for daylight, alarm, and other modes. These are associated with group of modules. For each Smart Controller module three select entities are created to give access to these values. User defined modes will be detected. The daylight mode control is deactivated by default as it usually is set automatically.

### Climate

Based on the first temperature setpoint and the sensor temperature, a climate controller is implemented. It supports heating on/off actions and its state can be used as input for automations. A manual on or off command will change the automatic operation for 5 minutes.

### Diagnostic values

Some values, e.g. the mdoule status, are implemented as diagnostic values. By default, they will be diabled. They can be found on the device panel and enabled there. Diagnostic entities are grouped in a seperate category, but they can be utilized as any other entity. The router provides some more diagnostic values, e.g. voltages, currents, and timeouts.

## Services

The Habitron integration supports a few services for system administration:

### Service `habitron.restart_module`

Restarts the module of the given address or restarts all modules if no argument is passed.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which serves the module.
| `mod_nmbr`              | yes       | The address of the habitron module, which shall be restarted. If FF, all modules will be restarted.

### Service `habitron.restart_router`

Restarts the habitron router.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which shall be restarted.

### Service `habitron.save_module_smc`

Saves a module's SMC data (module rules and names) to file. The file name is set automatically. It will appear in the config directory.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which serves the module.
| `mod_nmbr`              | no        | The address of the habitron module.

### Service `habitron.save_module_smg`

Saves a module's SMG data (module settings) to file. The file name is set automatically. It will appear in a data subdirectory of the habitron integration.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which serves the module.
| `mod_nmbr`              | no        | The address of the habitron module.

### Service `habitron.save_router_smr`

Saves a router's SMR data (router settings) to file. The file name is set automatically. It will appear in a data subdirectory of the habitron integration.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which serves the module.

### Service `habitron.save_module_status`

Saves a module's current status data (module input, output, sensor values) to file. The file name is set automatically ("*.mstat"). in a data subdirectory of the habitron integration.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which serves the module.
| `mod_nmbr`              | no        | The address of the habitron module.

### Service `habitron.save_router_status`

Saves a router's status data (router diagnostic values) to file. The file name is set automatically ("*.rstat"). in a data subdirectory of the habitron integration.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which serves the module.


## Unsupported

### Features

Multiple routers are not supported.

### Modules

The following modules are not supported:

- Smart Key fingerprint sensor

Not tested:
- Smart Dimm
- Unterputzmodul

