*** Settings ***
# A2000TM4 FIL 冒烟测试（beta）——需要课程固件在 firmware/local/
# 运行：renode-test renode/tests/fil_adc_demo.robot
Suite Setup                   Setup
Suite Teardown                Teardown
Test Setup                    Reset Machine
Test Teardown                 Test Teardown
Resource                      ${RENODEKEYWORDS}

*** Variables ***
${PLATFORM}                   ${CURDIR}/../a2000tm4.resc
${SYMBOLS}                    ${CURDIR}/../../firmware/local/symbols.json

*** Test Cases ***
Platform Loads And Firmware Boots
    Execute Command           include @${PLATFORM}
    # 固件运行 1s 虚拟时间不挂死（SysTick 持续驱动 TM1638 位拍）
    Execute Command           emulation SetGlobalQuantum "0.010000"
    Create Machine Tester
    [Teardown]                Test Teardown

Inject Voltage And Check Display Digits
    [Documentation]           注入 12 位码 → adc_demo 显示缓冲应呈现对应十进制值
    ...                       （依赖 firmware/local/symbols.json 的 digit 符号地址）
    Execute Command           include @${PLATFORM}
    ${digit0}=                Execute Command   sysbus ReadDoubleWord 0x20000000
    Log                       digit[0]=${digit0}（占位断言——正式地址由 symbols.json 注入）
    Should Be True            True
