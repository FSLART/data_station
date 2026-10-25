from glob import glob
from setuptools import find_packages, setup


setup(
    name="data_station_runtime",
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    package_data={"data_station_runtime": ["qml/*.qml"]},
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/data_station_runtime"]),
        ("share/data_station_runtime", ["package.xml"]),
        ("share/data_station_runtime/launch", glob("launch/*.launch.py")),
        ("share/data_station_runtime/config", glob("config/*.yaml")),
        ("share/data_station_runtime/dbc_signals", glob("../../dbc_signals/*_t26.dbc")),
    ],
    install_requires=["setuptools"],
    zip_safe=False,
    maintainer="LART",
    maintainer_email="lart@example.com",
    description="Runtime DBC acquisition, independent recording, and Qt Quick dashboard",
    license="MIT",
    entry_points={"console_scripts": [
        "runtime_can = data_station_runtime.can_node:main",
        "runtime_dashboard = data_station_runtime.app:main",
        "runtime_recorder = data_station_runtime.recorder:main",
    ]},
)
