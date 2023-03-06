<h2 align="center">
  <a href="https://habitron.de"><img src="./custom_components/habitron/logos/logo@2x.png" alt="Habitron logotype" width="300"></a>
  <br>
  <i>Home Assistant Habitron custom integration</i>
  <br>
</h2>

<p align="center">
  <a href="https://github.com/custom-components/hacs"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg"></a>
  <img src="https://img.shields.io/github/v/release/dneprojects/habitron" alt="Current version">
</p>

The `habitron` implementation allows you to integrate your [Habitron](https://www.habitron.de/) devices in Home Assistant. It is implemented using a _push_ model in _async_.

## Installation

### Manual install

```bash
# Download a copy of this repository
$ wget https://github.com/dneprojects/habitron/archive/master.zip

# Unzip the archive
$ unzip master.zip

# Move the habitron directory into your custom_components directory in your Home Assistant install
$ mv habitron-master/custom_components/habitron <home-assistant-install-directory>/config/custom_components/
```


### HACS install ([How to install HACS](https://hacs.xyz/docs/setup/prerequisites))

  1. Click on HACS in the Home Assistant menu
  2. Click on `Integrations`
  3. Click the top right menu (the three dots)
  4. Select `Custom repositories`
  5. Paste the repository URL (`https://github.com/dneprojects/habitron`) in the dialog box
  6. Select category `Integration`
  7. Click `Add`
  8. Click `Install` on the Habitron integration box that has now appeared


> :warning: **After executing one of the above installation methods, restart Home Assistant. Also clear your browser cache before proceeding to the next step, as the integration may not be visible otherwise.**


In your Home Assistant installation go to: Configuration > Integrations, click the button Add Integration > Habitron
Enter the details for your camera. The SMartIP, router and modules as devices.

## Configuration

For the habitron integration to work, the network interface SmartIP must be reachable via your local network. During configuration, the DNS hostname or the IP address has to given.
A second parameter is used to control the polling update interval.

| Configuration parameter | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `host name`             | no        | Either the DNS host name of the SmartIP or its IP address.
| `update interval`       | no        | Polling update interval in seconds, must be between 2 and 10 seconds.

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
| Temperature          | Temperature in the surrounding of the module.                 |
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

Saves a module's SMG data (module settings) to file. The file name is set automatically. It will appear in the config directory.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `rtr_nmbr`              | no        | The address of the habitron router, which serves the module.
| `mod_nmbr`              | no        | The address of the habitron module.

### Service `habitron.save_router_smr`

Saves a router's SMR data (router settings) to file. The file name is set automatically. It will appear in the config directory.

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
