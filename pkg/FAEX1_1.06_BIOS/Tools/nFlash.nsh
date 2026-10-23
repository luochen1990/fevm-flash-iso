@echo -off

set Afu_arg " /CAPSULE /P /B /N  /K  /L /X  /RLC:E"
#set Afu_arg " /P /B /N  /K  /L /X /RLC:E /reboot"
#set bin_path_name ".\BIOS.bin"
for %a in *bin
  set bin_path_name %a
endfor

if exist %bin_path_name% then
  echo Update BIOS: %bin_path_name%

  .\Tools\AfuEfix64.efi "%bin_path_name%" %Afu_arg%
else 
  ls
endif  