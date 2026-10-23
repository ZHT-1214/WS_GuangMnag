package com.wsplus.guide.amap

import android.content.Context
import com.amap.api.location.AMapLocationClient
import com.amap.api.maps.MapsInitializer
import com.amap.api.services.core.ServiceSettings

object AmapPrivacy {
    private const val PREFERENCES = "privacy_preferences"
    private const val AMAP_AGREED = "amap_agreed"

    fun hasAgreed(context: Context): Boolean =
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .getBoolean(AMAP_AGREED, false)

    fun agree(context: Context) {
        val appContext = context.applicationContext
        MapsInitializer.updatePrivacyShow(appContext, true, true)
        MapsInitializer.updatePrivacyAgree(appContext, true)
        AMapLocationClient.updatePrivacyShow(appContext, true, true)
        AMapLocationClient.updatePrivacyAgree(appContext, true)
        ServiceSettings.updatePrivacyShow(appContext, true, true)
        ServiceSettings.updatePrivacyAgree(appContext, true)

        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(AMAP_AGREED, true)
            .apply()
    }

    fun applySavedConsent(context: Context) {
        if (hasAgreed(context)) {
            agree(context)
        }
    }
}
