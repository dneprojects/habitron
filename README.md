<h2 align="center">
  <a href="https://habitron.de"><img src="./custom_components/habitron/logos/logo.png" alt="Habitron logotype" width="200"></a>
  <br>
  <i>Home Assistant Habitron custom integration</i>
  <br>
</h2>

<p align="center">
  <a href="https://github.com/custom-components/hacs"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg"></a>
  <img src="https://img.shields.io/github/v/release/dneprojects/habitron" alt="Current version">
</p>

The `habitron` implementation allows you to integrate your [Habitron](https://www.habitron.de/) devices in Home Assistant.

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
| `update interval`       | no        | Polling update interval in seconds, must be between 3 and 20 seconds.

## Services

The Habitron integration supports a few services for system administration:

### Service `habitron.restart_module`

Restarts the module of the given address or restarts all modules if no argument is passed.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| `mod_nmbr`              | yes       | The address of the habitron module, which shall be restarted.

### Service `habitron.restart_router`

Restarts the habitron router.

| Service data attribute  | Optional  | Description  |
| :---------------------- | :-------- | :----------- |
| None                    | no        | No parameter needed.

##Entities

According to the modules found, several entities will be created automatically.

### Lights

This integration creates light entities for all module outputs, dimmers. and LEDs. If covers are configured, the associated outputs will not appear as lights.

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

### Buttons

The habitron integration creates buttons for collective commands and visualization commands.

### Numbers

For Smart Controller modules, an input number entitiy is created to control the temperature setpoint.

### Select

The habitron system offers modes for daylight, alarm, and other modes. These are associated with group of modules. For each Smart Controller module three select entities are created to give access to these values. User defined modes will be detected.


## Unsupported modules

The following modules are not supported:

- Smart Key fingerprint sensor

Not tested:
- Smart Dimm
- Unterputzmodul
