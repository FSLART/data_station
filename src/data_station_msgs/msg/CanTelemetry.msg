# Raw data is present even when the CAN frame has no DBC definition.
std_msgs/Header header
string bus
string message
uint32 can_id
bool is_extended
bool is_remote
bool is_error
bool is_fd
bool bitrate_switch
bool error_state_indicator
uint8 dlc
uint8[] data
string dbc_sha256
data_station_msgs/SignalValue[] signals
