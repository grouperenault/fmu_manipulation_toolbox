--[[
Acknowledgement

dSPACE SE & Co. KG generously provides this script to the FMI-LS-BUS community. 
We would like to thank dSPACE for supporting the adoption of the FMI-LS-BUS standard 
and for contributing tools that help developers, integrators, and users work more 
effectively with FMI-LS-BUS-based systems.
]]

--[[
This header file declares bus-independent constants and data types as defined by the
FMI-LS-BUS layered standard specification (https://github.com/modelica/fmi-ls-bus).

It should be used when creating Network FMUs according to the FMI-LS-BUS layered standard.

Copyright (C) 2023-2026 Modelica Association Project "FMI"
              All rights reserved.

This file is licensed by the copyright holders under the 2-Clause BSD License
(https://opensource.org/licenses/BSD-2-Clause):

----------------------------------------------------------------------------
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

- Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
----------------------------------------------------------------------------
]]

local fmi_ls_bus = Proto("fmi_ls_bus", "FMI-LS-BUS")
local fmi_ls_bus_can = Proto("fmi_ls_bus_can", "FMI Layered Standard Bus (CAN)")
local fmi_ls_bus_lin = Proto("fmi_ls_bus_lin", "FMI Layered Standard Bus (LIN)")
local fmi_ls_bus_eth = Proto("fmi_ls_bus_eth", "FMI Layered Standard Bus (Ethernet)")
local fmi_ls_bus_flexray = Proto("fmi_ls_bus_flexray", "FMI Layered Standard Bus (FlexRay)")
local frame_comment = Field.new("frame.comment")

local fields = {
    opcode = ProtoField.uint32("fmi_ls_bus.opcode", "OP Code", base.HEX),
    operation_length = ProtoField.uint32("fmi_ls_bus.length", "Length", base.DEC),
    format_error_data_length = ProtoField.uint16("fmi_ls_bus.format_error.data_length", "Data Length", base.DEC),
    format_error_data = ProtoField.bytes("fmi_ls_bus.format_error.data", "Data"),

    can_id = ProtoField.uint32("fmi_ls_bus.can.id", "ID", base.HEX),
    can_ide = ProtoField.bool("fmi_ls_bus.can.ide", "Ide"),
    can_rtr = ProtoField.bool("fmi_ls_bus.can.rtr", "Rtr"),
    can_brs = ProtoField.bool("fmi_ls_bus.can_fd.brs", "Brs"),
    can_esi = ProtoField.bool("fmi_ls_bus.can_fd.esi", "Esi"),
    can_sec = ProtoField.bool("fmi_ls_bus.can_xl.sec", "Sec"),
    can_sdt = ProtoField.uint8("fmi_ls_bus.can_xl.sdt", "SDT", base.HEX),
    can_vcid = ProtoField.uint8("fmi_ls_bus.can_xl.vcid", "VCID", base.HEX),
    can_acceptance_field = ProtoField.uint32("fmi_ls_bus.can_xl.af", "AF", base.HEX),
    can_data_length = ProtoField.uint16("fmi_ls_bus.can.data_length", "Data Length", base.DEC),
    can_data = ProtoField.bytes("fmi_ls_bus.can.data", "Data"),
    can_error_code = ProtoField.uint8("fmi_ls_bus.can.error_code", "Error Code", base.HEX,
        {[0x01] = "Bit error", [0x02] = "Bit stuffing error", [0x03] = "Form error", [0x04] = "CRC error",
         [0x05] = "ACK error", [0x06] = "Broken error frame"}),
    can_error_flag = ProtoField.uint8("fmi_ls_bus.can.error_flag", "Error Flag", base.HEX,
        {[0x01] = "Primary error flag", [0x02] = "Secondary error flag"}),
    can_is_sender = ProtoField.bool("fmi_ls_bus.can.is_sender", "Is Sender"),
    can_status = ProtoField.uint8("fmi_ls_bus.can.status", "Status", base.HEX,
        {[0x01] = "Error active", [0x02] = "Error passive", [0x03] = "Bus off"}),
    can_parameter_type = ProtoField.uint8("fmi_ls_bus.can.parameter_type", "Parameter Type", base.HEX,
        {[0x01] = "CAN baud rate", [0x02] = "CAN FD baud rate", [0x03] = "CAN XL baud rate", [0x04] = "Arbitration lost behavior"}),
    can_baudrate = ProtoField.uint32("fmi_ls_bus.can.baudrate", "Baud Rate", base.DEC),
    can_arbitration_lost_behavior = ProtoField.uint8("fmi_ls_bus.can.arbitration_lost_behavior", "Arbitration Lost Behavior", base.HEX,
        {[0x01] = "Buffer and retransmit", [0x02] = "Discard and notify"}),

    lin_frame_part = ProtoField.uint8("fmi_ls_bus.lin.frame_part", "Frame Part", base.HEX,
        {[0x01] = "Header", [0x02] = "Response"}),
    lin_id = ProtoField.uint8("fmi_ls_bus.lin.id", "ID", base.HEX),
    lin_checksum_type = ProtoField.uint8("fmi_ls_bus.lin.checksum_type", "Checksum Type", base.HEX,
        {[0x01] = "Classic checksum", [0x02] = "Enhanced checksum"}),
    lin_data_length = ProtoField.uint8("fmi_ls_bus.lin.data_length", "Data Length", base.DEC),
    lin_data = ProtoField.bytes("fmi_ls_bus.lin.data", "Data"),
    lin_error_code = ProtoField.uint8("fmi_ls_bus.lin.error_code", "Error Code", base.HEX,
        {[0x01] = "Bit error", [0x02] = "Checksum error", [0x03] = "Identifier parity error", [0x04] = "No response error",
         [0x05] = "Synch field error", [0x06] = "Synch tolerance error", [0x07] = "Header timeout error",
         [0x08] = "Frame error", [0x09] = "Physical bus error"}),
    lin_parameter_type = ProtoField.uint8("fmi_ls_bus.lin.parameter_type", "Parameter Type", base.HEX,
        {[0x01] = "Baud rate", [0x02] = "Node type"}),
    lin_baudrate = ProtoField.uint32("fmi_ls_bus.lin.baudrate", "Baud Rate", base.DEC),
    lin_node_type = ProtoField.uint8("fmi_ls_bus.lin.node_type", "Node Type", base.HEX,
        {[0x01] = "LIN Commander", [0x02] = "LIN Responder"}),

    eth_start_delimiter = ProtoField.uint8("fmi_ls_bus.eth.start_delimiter", "Start Delimiter", base.HEX),
    eth_fragment_counter = ProtoField.uint8("fmi_ls_bus.eth.fragment_counter", "Fragment Counter", base.DEC),
    eth_last_fragment = ProtoField.bool("fmi_ls_bus.eth.last_fragment", "Last Fragment"),
    eth_destination = ProtoField.ether("fmi_ls_bus.eth.destination", "Destination Address"),
    eth_source = ProtoField.ether("fmi_ls_bus.eth.source", "Source Address"),
    eth_type_or_length = ProtoField.uint16("fmi_ls_bus.eth.type_or_length", "Type or Length", base.HEX),
    eth_data_length = ProtoField.uint32("fmi_ls_bus.eth.data_length", "Data Length", base.DEC),
    eth_data = ProtoField.bytes("fmi_ls_bus.eth.data", "Data"),
    eth_error_code = ProtoField.uint8("fmi_ls_bus.eth.error_code", "Error Code", base.HEX,
        {[0x00] = "Unknown", [0x01] = "Medium busy", [0x02] = "Collision"}),
    eth_is_sender = ProtoField.bool("fmi_ls_bus.eth.is_sender", "Is Sender"),
    eth_parameter_type = ProtoField.uint8("fmi_ls_bus.eth.parameter_type", "Parameter Type", base.HEX,
        {[0x00] = "Supported PHY types"}),
    eth_mdi_mode = ProtoField.uint8("fmi_ls_bus.eth.mdi_mode", "MDI Mode", base.HEX,
        {[0x00] = "None", [0x01] = "MDI", [0x02] = "MDI-X", [0x03] = "Auto MDI-X"}),
    eth_phy_types_length = ProtoField.uint16("fmi_ls_bus.eth.phy_types_length", "Supported PHY Types Length", base.DEC),
    eth_phy_types = ProtoField.string("fmi_ls_bus.eth.phy_types", "Supported PHY Types"),

    flexray_cycle_id = ProtoField.uint8("fmi_ls_bus.flexray.cycle_id", "Cycle ID", base.DEC),
    flexray_slot_id = ProtoField.uint16("fmi_ls_bus.flexray.slot_id", "Slot ID", base.DEC),
    flexray_channel = ProtoField.uint8("fmi_ls_bus.flexray.channel", "Channel", base.HEX,
        {[0x01] = "Channel A", [0x02] = "Channel B", [0x03] = "Channels A and B"}),
    flexray_startup_frame = ProtoField.bool("fmi_ls_bus.flexray.startup_frame", "Startup Frame Indicator"),
    flexray_sync_frame = ProtoField.bool("fmi_ls_bus.flexray.sync_frame", "Sync Frame Indicator"),
    flexray_null_frame = ProtoField.bool("fmi_ls_bus.flexray.null_frame", "Null Frame Indicator"),
    flexray_payload_preamble = ProtoField.bool("fmi_ls_bus.flexray.payload_preamble", "Payload Preamble Indicator"),
    flexray_data_length = ProtoField.uint8("fmi_ls_bus.flexray.data_length", "Data Length", base.DEC),
    flexray_data = ProtoField.bytes("fmi_ls_bus.flexray.data", "Data"),
    flexray_error_flags = ProtoField.uint8("fmi_ls_bus.flexray.error_flags", "Error Flags", base.HEX),
    flexray_segment_indicator = ProtoField.uint16("fmi_ls_bus.flexray.segment_indicator", "Segment Indicator", base.HEX,
        {[0xFFFE] = "Symbol window", [0xFFFF] = "Network idle time"}),
    flexray_parameter_type = ProtoField.uint8("fmi_ls_bus.flexray.parameter_type", "Parameter Type", base.HEX,
        {[0x01] = "FlexRay configuration"}),
    flexray_macrotick_duration = ProtoField.uint32("fmi_ls_bus.flexray.macrotick_duration", "Macrotick Duration", base.DEC),
    flexray_macroticks_per_cycle = ProtoField.uint16("fmi_ls_bus.flexray.macroticks_per_cycle", "Macroticks per Cycle", base.DEC),
    flexray_cycle_count_max = ProtoField.uint8("fmi_ls_bus.flexray.cycle_count_max", "Cycle Count Max", base.DEC),
    flexray_action_point_offset = ProtoField.uint8("fmi_ls_bus.flexray.action_point_offset", "ActionPoint Offset", base.DEC),
    flexray_static_slot_length = ProtoField.uint16("fmi_ls_bus.flexray.static_slot_length", "Static Slot Length", base.DEC),
    flexray_number_of_static_slots = ProtoField.uint16("fmi_ls_bus.flexray.number_of_static_slots", "Number of Static Slots", base.DEC),
    flexray_static_payload_length = ProtoField.uint8("fmi_ls_bus.flexray.static_payload_length", "Static Payload Length", base.DEC),
    flexray_minislot_action_point_offset = ProtoField.uint8("fmi_ls_bus.flexray.minislot_action_point_offset", "Minislot ActionPoint Offset", base.DEC),
    flexray_number_of_minislots = ProtoField.uint16("fmi_ls_bus.flexray.number_of_minislots", "Number of Minislots", base.DEC),
    flexray_minislot_length = ProtoField.uint8("fmi_ls_bus.flexray.minislot_length", "Minislot Length", base.DEC),
    flexray_maximum_dynamic_payload_length = ProtoField.uint8("fmi_ls_bus.flexray.maximum_dynamic_payload_length", "Maximum Dynamic Payload Length", base.DEC),
    flexray_symbol_action_point_offset = ProtoField.uint8("fmi_ls_bus.flexray.symbol_action_point_offset", "Symbol ActionPoint Offset", base.DEC),
    flexray_symbol_window_length = ProtoField.uint8("fmi_ls_bus.flexray.symbol_window_length", "Symbol Window Length", base.DEC),
    flexray_nit_length = ProtoField.uint16("fmi_ls_bus.flexray.nit_length", "NIT Length", base.DEC),
    flexray_nm_vector_length = ProtoField.uint8("fmi_ls_bus.flexray.nm_vector_length", "NM Vector Length", base.DEC),
    flexray_dynamic_slot_idle_time = ProtoField.uint32("fmi_ls_bus.flexray.dynamic_slot_idle_time", "Dynamic Slot Idle Time", base.DEC),
    flexray_coldstart_node = ProtoField.uint8("fmi_ls_bus.flexray.coldstart_node", "Coldstart Node", base.HEX,
        {[0x01] = "None", [0x02] = "TT-D", [0x03] = "TT-E", [0x04] = "TT-L"}),
    flexray_start_time = ProtoField.uint64("fmi_ls_bus.flexray.start_time", "Start Time", base.DEC),
    flexray_symbol_type = ProtoField.uint8("fmi_ls_bus.flexray.symbol_type", "Type", base.HEX,
        {[0x01] = "Collision avoidance symbol", [0x02] = "Media test symbol", [0x03] = "Wakeup symbol"})
}

fmi_ls_bus.fields = fields

local function add_bytes(tree, field, buffer, offset, length, operation_length)
    if length > 0 and offset + length <= operation_length then
        tree:add(field, buffer(offset, length))
    end
end

local function add_le(tree, field, buffer, offset, length, operation_length)
    if offset + length <= operation_length then
        tree:add_le(field, buffer(offset, length))
    end
end

local function add_data(tree, field, buffer, data_length_offset, data_length_size, data_offset, operation_length)
    if data_length_offset + data_length_size <= operation_length then
        local data_length = buffer(data_length_offset, data_length_size):le_uint()
        add_bytes(tree, field, buffer, data_offset, math.min(data_length, math.max(operation_length - data_offset, 0)), operation_length)
    end
end

local function decode_format_error(tree, buffer, operation_length)
    add_le(tree, fields.format_error_data_length, buffer, 8, 2, operation_length)
    add_data(tree, fields.format_error_data, buffer, 8, 2, 10, operation_length)
end

local function decode_can(tree, buffer, operation_code, operation_length)
    if operation_code == 0x01 then
        decode_format_error(tree, buffer, operation_length)
    elseif operation_code == 0x10 then
        add_le(tree, fields.can_id, buffer, 8, 4, operation_length)
        add_bytes(tree, fields.can_ide, buffer, 12, 1, operation_length)
        add_bytes(tree, fields.can_rtr, buffer, 13, 1, operation_length)
        add_le(tree, fields.can_data_length, buffer, 14, 2, operation_length)
        add_data(tree, fields.can_data, buffer, 14, 2, 16, operation_length)
    elseif operation_code == 0x11 then
        add_le(tree, fields.can_id, buffer, 8, 4, operation_length)
        add_bytes(tree, fields.can_ide, buffer, 12, 1, operation_length)
        add_bytes(tree, fields.can_brs, buffer, 13, 1, operation_length)
        add_bytes(tree, fields.can_esi, buffer, 14, 1, operation_length)
        add_le(tree, fields.can_data_length, buffer, 15, 2, operation_length)
        add_data(tree, fields.can_data, buffer, 15, 2, 17, operation_length)
    elseif operation_code == 0x12 then
        add_le(tree, fields.can_id, buffer, 8, 4, operation_length)
        add_bytes(tree, fields.can_ide, buffer, 12, 1, operation_length)
        add_bytes(tree, fields.can_sec, buffer, 13, 1, operation_length)
        add_bytes(tree, fields.can_sdt, buffer, 14, 1, operation_length)
        add_bytes(tree, fields.can_vcid, buffer, 15, 1, operation_length)
        add_le(tree, fields.can_acceptance_field, buffer, 16, 4, operation_length)
        add_le(tree, fields.can_data_length, buffer, 20, 2, operation_length)
        add_data(tree, fields.can_data, buffer, 20, 2, 22, operation_length)
    elseif operation_code == 0x20 or operation_code == 0x30 then
        add_le(tree, fields.can_id, buffer, 8, 4, operation_length)
    elseif operation_code == 0x31 then
        add_le(tree, fields.can_id, buffer, 8, 4, operation_length)
        add_bytes(tree, fields.can_error_code, buffer, 12, 1, operation_length)
        add_bytes(tree, fields.can_error_flag, buffer, 13, 1, operation_length)
        add_bytes(tree, fields.can_is_sender, buffer, 14, 1, operation_length)
    elseif operation_code == 0x40 then
        add_bytes(tree, fields.can_parameter_type, buffer, 8, 1, operation_length)
        if operation_length >= 9 then
            local parameter_type = buffer(8, 1):uint()
            if parameter_type >= 0x01 and parameter_type <= 0x03 then
                add_le(tree, fields.can_baudrate, buffer, 9, 4, operation_length)
            elseif parameter_type == 0x04 then
                add_bytes(tree, fields.can_arbitration_lost_behavior, buffer, 9, 1, operation_length)
            end
        end
    elseif operation_code == 0x41 then
        add_bytes(tree, fields.can_status, buffer, 8, 1, operation_length)
    end
end

local function decode_lin(tree, buffer, operation_code, operation_length)
    if operation_code == 0x01 then
        decode_format_error(tree, buffer, operation_length)
    elseif operation_code == 0x10 then
        add_bytes(tree, fields.lin_frame_part, buffer, 8, 1, operation_length)
        add_bytes(tree, fields.lin_id, buffer, 9, 1, operation_length)
        add_bytes(tree, fields.lin_checksum_type, buffer, 10, 1, operation_length)
        add_bytes(tree, fields.lin_data_length, buffer, 11, 1, operation_length)
        add_data(tree, fields.lin_data, buffer, 11, 1, 12, operation_length)
    elseif operation_code == 0x20 then
        add_bytes(tree, fields.lin_id, buffer, 8, 1, operation_length)
    elseif operation_code == 0x30 then
        add_bytes(tree, fields.lin_id, buffer, 8, 1, operation_length)
        add_bytes(tree, fields.lin_error_code, buffer, 9, 1, operation_length)
    elseif operation_code == 0x40 then
        add_bytes(tree, fields.lin_parameter_type, buffer, 8, 1, operation_length)
        if operation_length >= 9 then
            local parameter_type = buffer(8, 1):uint()
            if parameter_type == 0x01 then
                add_le(tree, fields.lin_baudrate, buffer, 9, 4, operation_length)
            elseif parameter_type == 0x02 then
                add_bytes(tree, fields.lin_node_type, buffer, 9, 1, operation_length)
            end
        end
    end
end

local function decode_eth(tree, buffer, operation_code, operation_length)
    if operation_code == 0x01 then
        decode_format_error(tree, buffer, operation_length)
    elseif operation_code == 0x10 then
        add_bytes(tree, fields.eth_start_delimiter, buffer, 8, 1, operation_length)
        add_bytes(tree, fields.eth_fragment_counter, buffer, 9, 1, operation_length)
        add_bytes(tree, fields.eth_last_fragment, buffer, 10, 1, operation_length)
        add_bytes(tree, fields.eth_destination, buffer, 11, 6, operation_length)
        add_bytes(tree, fields.eth_source, buffer, 17, 6, operation_length)
        add_le(tree, fields.eth_type_or_length, buffer, 23, 2, operation_length)
        add_le(tree, fields.eth_data_length, buffer, 25, 4, operation_length)
        add_data(tree, fields.eth_data, buffer, 25, 4, 29, operation_length)
    elseif operation_code == 0x30 then
        add_bytes(tree, fields.eth_error_code, buffer, 8, 1, operation_length)
        add_bytes(tree, fields.eth_is_sender, buffer, 9, 1, operation_length)
    elseif operation_code == 0x40 then
        add_bytes(tree, fields.eth_parameter_type, buffer, 8, 1, operation_length)
        add_bytes(tree, fields.eth_mdi_mode, buffer, 9, 1, operation_length)
        add_le(tree, fields.eth_phy_types_length, buffer, 10, 2, operation_length)
        if operation_length >= 12 then
            local phy_types_length = buffer(10, 2):le_uint()
            add_bytes(tree, fields.eth_phy_types, buffer, 12, math.min(phy_types_length, operation_length - 12), operation_length)
        end
    end
end

local function decode_flexray(tree, buffer, operation_code, operation_length)
    if operation_code == 0x01 then
        decode_format_error(tree, buffer, operation_length)
    elseif operation_code == 0x10 then
        add_bytes(tree, fields.flexray_cycle_id, buffer, 8, 1, operation_length)
        add_le(tree, fields.flexray_slot_id, buffer, 9, 2, operation_length)
        add_bytes(tree, fields.flexray_channel, buffer, 11, 1, operation_length)
        add_bytes(tree, fields.flexray_startup_frame, buffer, 12, 1, operation_length)
        add_bytes(tree, fields.flexray_sync_frame, buffer, 13, 1, operation_length)
        add_bytes(tree, fields.flexray_null_frame, buffer, 14, 1, operation_length)
        add_bytes(tree, fields.flexray_payload_preamble, buffer, 15, 1, operation_length)
        add_bytes(tree, fields.flexray_data_length, buffer, 16, 1, operation_length)
        add_data(tree, fields.flexray_data, buffer, 16, 1, 17, operation_length)
    elseif operation_code == 0x11 or operation_code == 0x12 then
        add_bytes(tree, fields.flexray_cycle_id, buffer, 8, 1, operation_length)
        add_le(tree, fields.flexray_slot_id, buffer, 9, 2, operation_length)
        add_bytes(tree, fields.flexray_channel, buffer, 11, 1, operation_length)
    elseif operation_code == 0x20 then
        add_bytes(tree, fields.flexray_error_flags, buffer, 8, 1, operation_length)
        add_bytes(tree, fields.flexray_cycle_id, buffer, 9, 1, operation_length)
        add_le(tree, fields.flexray_segment_indicator, buffer, 10, 2, operation_length)
        add_bytes(tree, fields.flexray_channel, buffer, 12, 1, operation_length)
    elseif operation_code == 0x30 then
        add_bytes(tree, fields.flexray_parameter_type, buffer, 8, 1, operation_length)
        add_le(tree, fields.flexray_macrotick_duration, buffer, 9, 4, operation_length)
        add_le(tree, fields.flexray_macroticks_per_cycle, buffer, 13, 2, operation_length)
        add_bytes(tree, fields.flexray_cycle_count_max, buffer, 15, 1, operation_length)
        add_bytes(tree, fields.flexray_action_point_offset, buffer, 16, 1, operation_length)
        add_le(tree, fields.flexray_static_slot_length, buffer, 17, 2, operation_length)
        add_le(tree, fields.flexray_number_of_static_slots, buffer, 19, 2, operation_length)
        add_bytes(tree, fields.flexray_static_payload_length, buffer, 21, 1, operation_length)
        add_bytes(tree, fields.flexray_minislot_action_point_offset, buffer, 22, 1, operation_length)
        add_le(tree, fields.flexray_number_of_minislots, buffer, 23, 2, operation_length)
        add_bytes(tree, fields.flexray_minislot_length, buffer, 25, 1, operation_length)
        add_bytes(tree, fields.flexray_maximum_dynamic_payload_length, buffer, 26, 1, operation_length)
        add_bytes(tree, fields.flexray_symbol_action_point_offset, buffer, 27, 1, operation_length)
        add_bytes(tree, fields.flexray_symbol_window_length, buffer, 28, 1, operation_length)
        add_le(tree, fields.flexray_nit_length, buffer, 29, 2, operation_length)
        add_bytes(tree, fields.flexray_nm_vector_length, buffer, 31, 1, operation_length)
        add_le(tree, fields.flexray_dynamic_slot_idle_time, buffer, 32, 4, operation_length)
        add_bytes(tree, fields.flexray_coldstart_node, buffer, 36, 1, operation_length)
    elseif operation_code == 0x40 then
        add_le(tree, fields.flexray_start_time, buffer, 8, 8, operation_length)
    elseif operation_code == 0x50 then
        add_bytes(tree, fields.flexray_cycle_id, buffer, 8, 1, operation_length)
        add_bytes(tree, fields.flexray_channel, buffer, 9, 1, operation_length)
        add_bytes(tree, fields.flexray_symbol_type, buffer, 10, 1, operation_length)
        add_le(tree, fields.flexray_slot_id, buffer, 11, 2, operation_length)
    end
end

local decoders = {
    can = decode_can,
    lin = decode_lin,
    eth = decode_eth,
    flexray = decode_flexray
}

local operation_names = {
    can = {[0x01] = "Format Error", [0x10] = "CAN Transmit", [0x11] = "CAN FD Transmit", [0x12] = "CAN XL Transmit",
           [0x20] = "CAN Confirm", [0x30] = "CAN Arbitration Lost", [0x31] = "CAN Bus Error", [0x40] = "CAN Configuration",
           [0x41] = "CAN Status", [0x42] = "CAN Wakeup"},
    lin = {[0x01] = "Format Error", [0x10] = "LIN Transmit", [0x20] = "LIN Confirm", [0x30] = "LIN Bus Error",
           [0x40] = "LIN Configuration", [0x41] = "LIN Wakeup", [0x50] = "LIN Wakeup"},
    eth = {[0x01] = "Format Error", [0x10] = "Ethernet Transmit", [0x20] = "Ethernet Confirm", [0x30] = "Ethernet Bus Error",
           [0x40] = "Ethernet Configuration", [0x41] = "Ethernet Wakeup"},
    flexray = {[0x01] = "Format Error", [0x10] = "FlexRay Transmit", [0x11] = "FlexRay Cancel", [0x12] = "FlexRay Confirm",
               [0x20] = "FlexRay Bus Error", [0x30] = "FlexRay Configuration", [0x40] = "FlexRay Start Communication",
               [0x50] = "FlexRay Symbol"}
}

local function operation_status_from_comments()
    for _, comment_field in ipairs({frame_comment()}) do
        local comment = tostring(comment_field)
        local unsupported_reason = comment:match("^%s*Unsupported:%s*(.*)$")
        if unsupported_reason ~= nil then
            return unsupported_reason ~= "" and unsupported_reason or "Operation is not supported", nil
        end

        local ignored_reason = comment:match("^%s*Ignored:%s*(.*)$")
        if ignored_reason ~= nil then
            return nil, ignored_reason ~= "" and ignored_reason or "Operation was ignored"
        end
    end
end

local function dissect(protocol, buffer, pinfo, tree)
    if buffer:len() < 8 then
        return 0
    end

    local operation_code = buffer(0, 4):le_uint()
    local declared_length = buffer(4, 4):le_uint()
    local operation_length = math.min(declared_length, buffer:len())
    local operation_name = operation_names[protocol][operation_code]

    if operation_name == nil then
        return 0
    end

    local unsupported_reason, ignored_reason = operation_status_from_comments()
    local is_unsupported = unsupported_reason ~= nil
    local is_ignored = ignored_reason ~= nil

    local displayed_length = math.max(operation_length, 8)
    local subtree = tree:add(fmi_ls_bus, buffer(0, displayed_length), "FMI-LS-BUS Operation")
    subtree:set_text("FMI-LS-BUS Operation: " .. operation_name)
    subtree:add_le(fields.opcode, buffer(0, 4))
    subtree:add_le(fields.operation_length, buffer(4, 4))
    decoders[protocol](subtree, buffer, operation_code, operation_length)

    pinfo.cols.protocol = "FMI-LS-BUS"
    local status_tag = is_ignored and " [Ignored]" or (is_unsupported and " [Unsupported]" or "")
    pinfo.cols.info = string.format("%s%s (0x%04X)", operation_name, status_tag, operation_code)

    if is_unsupported then
        subtree:add_expert_info(PI_UNDECODED, PI_WARN, unsupported_reason)
    end
    if is_ignored then
        subtree:add_expert_info(PI_UNDECODED, PI_WARN, ignored_reason)
    end
    if declared_length < 8 then
        subtree:add_expert_info(PI_MALFORMED, PI_ERROR, "Operation length is smaller than the 8-byte header")
    end
    if declared_length > buffer:len() then
        subtree:add_expert_info(PI_MALFORMED, PI_ERROR, "Operation length exceeds captured data")
    end

    return displayed_length
end

function fmi_ls_bus.dissector()
    return 0
end

function fmi_ls_bus_can.dissector(buffer, pinfo, tree)
    return dissect("can", buffer, pinfo, tree)
end

function fmi_ls_bus_lin.dissector(buffer, pinfo, tree)
    return dissect("lin", buffer, pinfo, tree)
end

function fmi_ls_bus_eth.dissector(buffer, pinfo, tree)
    return dissect("eth", buffer, pinfo, tree)
end

function fmi_ls_bus_flexray.dissector(buffer, pinfo, tree)
    return dissect("flexray", buffer, pinfo, tree)
end

-- DLT 252 exported-PDU packets select a protocol through their PROTO_NAME TLV.
-- Writers must use fmi_ls_bus_can, fmi_ls_bus_lin, fmi_ls_bus_eth, or fmi_ls_bus_flexray.
return fmi_ls_bus
