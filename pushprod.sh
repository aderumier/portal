bash build-deb.sh
tsc
scp -P 8735 batocera-games-catalog_1.0.0_all.deb root@rgs-retro.ddns.net:/root/
ssh  -P 8735 root@rgs-retro.ddns.net 'dpkg -i batocera-games-catalog_1.0.0_all.deb'
tailscale down
scp -r services/download_service batocera:/userdata/system/rgs/
ssh root@batocera '/userdata/system/services/rgs_download stop && /userdata/system/services/rgs_download start'
