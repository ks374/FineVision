#ifndef _EYECONTROL_SDK_H
#define _EYECONTROL_SDK_H

#define EYE_CONTROL_EXPORT  __declspec(dllexport)
#include <string>


/*===========================================
	获取眼动数据的数据结构
============================================*/
struct stEyeCtl_EyeDataEx
{
	double xm;				// 原始眼动点X
	double ym;				// 原始眼动点Y

	double xl;					// 原始左眼动点X
	double yl;					// 原始左眼动点Y
	double xr;					// 原始右眼动点X
	double yr;					// 原始右眼动点Y

	double l_area;				// 左眼瞳孔面积
	double r_area;				// 有眼瞳孔面积

	int	i32LeftEyePosX;			// 左眼相对显示器的位置X
	int	i32LeftEyePosY;			// 左眼相对显示器的位置Y
	int	i32RightEyePosX;		// 右眼相对显示器的位置X
	int i32RightEyePosY;		// 右眼相对显示器的位置Y

	int	nCalibrationStatus;
	int returnValue;

	double  frame_time;			// frame time
};

struct stEyeCtl_EyeDataPos
{
	double fPoslx;
	double fPosly;
	double fPosrx;
	double fPosry;
	double fPosl1x;
	double fPosl1y;
	double fPosr1x;
	double fPosr1y;
	double fPosl2x;
	double fPosl2y;
	double fPosr2x;
	double fPosr2y;
};

// 函数接口功能
/*===========================================
功能：打开眼动仪
返回值说明：成功返回TRUE，失败返回FALSE
============================================*/
EXTERN_C EYE_CONTROL_EXPORT BOOL EyeControl_Init(int FrameRate = 100);
/*===========================================
功能：获取眼动数据
参数说明：参考stEyeCtl_EyeDataEx
返回值说明：返回1成功获取到眼动数据，返回0/-1 正在计算或失败
============================================*/
EXTERN_C EYE_CONTROL_EXPORT int EyeControl_GetEyeDataEx(stEyeCtl_EyeDataEx *stEyeData);

/*===========================================
功能：开始校准
参数说明：1.bUI设置为TRUE,nIndex设置任意值，使用SDK默认校准逻辑与UI
		  2.bUI设置为FALSE, nIndex设置为校准值，即校准对应的校准点，校准次序：5->4->6->2->8->1->3->7->9
		    调用EyeControl_GetEyeDataEx接口获取stEyeCtl_EyeDataEx校准状态nCalibrationStatus，
			未校准状态nCalibrationStatus的值为0，校准成功后返回校准值(5->4->6->2->8->1->3->7->9)。
============================================*/
EXTERN_C EYE_CONTROL_EXPORT void EyeControl_StartCalibration(BOOL bUI, int eyeMode, int nIndex);
EXTERN_C EYE_CONTROL_EXPORT void EyeControl_StartCalibrationEndIndex(BOOL bUI = TRUE, int eyeMode = 0, int nIndex = 0, int endIndex = 9);
/*===========================================
功能：停止校准  
============================================*/
EXTERN_C EYE_CONTROL_EXPORT void EyeControl_StopCalibration();

EXTERN_C EYE_CONTROL_EXPORT void SetGetDataEyeMode(int eyeMode = 0);

EXTERN_C EYE_CONTROL_EXPORT float EyeControl_GetCameraFps();

EXTERN_C EYE_CONTROL_EXPORT void EyeControl_SaveImg();

EXTERN_C EYE_CONTROL_EXPORT void EyeControl_StartRecognition();

EXTERN_C EYE_CONTROL_EXPORT void EyeControl_StopRecognition();

//显示图像
EXTERN_C EYE_CONTROL_EXPORT void EyeControl_Display();

//关闭图像
EXTERN_C EYE_CONTROL_EXPORT void EyeControl_Destory();

/*===========================================
功能：获取图像数据
参数说明：pBuf为调用前申请的内存区域。调用后图像数据填充在pBuf中，
		  眼动仪图像分辨率为1920*1200，nBufWidth、nBufHeight返回值分别为1920、1200
返回值说明：返回TRUE获取成功，返回FALSE获取失败
============================================*/
EXTERN_C EYE_CONTROL_EXPORT	BOOL EyeControl_GetImageBuffer(BYTE * &pBuf, BYTE * &partBuf, int *nBufWidth, int *nBufHeight, BYTE * &leftBuf, BYTE * &rightBuf, int *eyeBufWidth, int *eyeBufHeight);

/*===========================================
功能：关闭眼动仪器
============================================*/
EXTERN_C EYE_CONTROL_EXPORT void EyeControl_Close();

#endif