plugins {
    id("com.android.application")
}

android {
    namespace = "com.openxiaoai.tvhelper"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.openxiaoai.tvhelper"
        minSdk = 28
        // Runs on the TV's Android 11, as the adb shell user (tv-helper.sh).
        targetSdk = 30
        versionCode = 5
        versionName = "0.3.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
