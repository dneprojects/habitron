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

The `habitron` implementation allows you to integrate your [Habitron](https://www.habitron.de/) devices in Home Assistant. It is implemented using a _polling_ model in _async_.

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

## More Information

More information can be found <a href="./custom_components/habitron/README.md">here</a>.

