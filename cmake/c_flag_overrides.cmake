if(MSVC)
	# /guard:cf: Control Flow Guard。這些 DLL 會被載入到任何含文字輸入框的行程
	# （含瀏覽器 sandbox renderer），一旦碼表/協定解析程式碼出現記憶體錯誤，
	# CFG 可限制間接呼叫被劫持利用的範圍。/GS、/DYNAMICBASE、/NXCOMPAT 為 MSVC
	# 預設已開啟，此處補上需顯式宣告的 CFG。
	set(CMAKE_C_FLAGS_DEBUG_INIT "/D_DEBUG /MDd /Zi /Ob0 /Od /RTC1 /guard:cf")
	set(CMAKE_C_FLAGS_MINSIZEREL_INIT     "/MT /O1 /Ob1 /D NDEBUG /guard:cf")
	set(CMAKE_C_FLAGS_RELEASE_INIT        "/MT /O2 /Ob2 /D NDEBUG /guard:cf")
	set(CMAKE_C_FLAGS_RELWITHDEBINFO_INIT "/MD /Zi /O2 /Ob1 /D NDEBUG /guard:cf")
endif()
