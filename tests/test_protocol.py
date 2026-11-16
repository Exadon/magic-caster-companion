import struct

from mcwand import Box, ImuSample, Wand


def test_wand_parses_touch_firmware_and_model():
    w = Wand("00:00:00:00:00:00")
    touches = []
    w.on_touch = touches.append
    w._handle(None, bytearray([0x10, 0xF5]))
    assert touches == [0x05]
    w._handle(None, bytearray([0x00, 0x00, 0x03]))
    assert w.firmware == "0.3"
    w._handle(None, bytearray([0x0E, 0x04]) + b"WBMC22G1SHRW")
    assert w.model == "WBMC22G1SHRW"


def test_wand_parses_imu_samples():
    w = Wand("00:00:00:00:00:00")
    got = []
    w.on_imu = got.extend
    pkt = (bytearray([0x2C, 0, 0, 2]) + struct.pack("<6h", 0, 0, 100, 2048, 0, 0)
           + struct.pack("<6h", 1, 2, 3, 0, 0, 2048))
    w._handle(None, pkt)
    assert len(got) == 2 and isinstance(got[0], ImuSample)
    assert abs(got[0].accel[0] - 1.0) < 1e-6 and abs(got[1].accel[2] - 1.0) < 1e-6
    assert abs(got[0].gyro[2] - 100 * 0.0010908308) < 1e-9


def test_wand_ignores_truncated_imu():
    w = Wand("00:00:00:00:00:00")
    got = []
    w.on_imu = got.extend
    w._handle(None, bytearray([0x2C, 0, 0, 5, 1, 2, 3]))
    assert got == []


def test_box_events():
    b = Box("00:00:00:00:00:00")
    lid, wand, usb = [], [], []
    b.on_lid, b.on_wand, b.on_charge = lid.append, wand.append, usb.append
    b._handle(None, bytearray([0x10, 0x03]))   # combined status: lid removed + wand present
    assert lid == [True] and wand == [True]
    b._handle(None, bytearray([0x11, 0x00]))   # lid back on
    b._handle(None, bytearray([0x12, 0x00]))   # wand removed
    b._handle(None, bytearray([0x13, 0x01]))   # USB power
    assert lid[-1] is False and wand[-1] is False and usb == [True]


def test_device_uuids_differ_between_wand_and_box():
    assert Wand("x").cmd_uuid != Box("x").cmd_uuid
    assert Wand("x").notify_uuid.startswith("57420003")
