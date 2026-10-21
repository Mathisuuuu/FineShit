// =============================================================================
//  NexusGroupeLogique.cs   (NinjaTrader 8 / NinjaScript - bibliotheque)
//
//  Logique des strategies du Groupe, sans aucun type NinjaTrader : la meme
//  classe tourne dans NinjaTrader (Strategies\NexusGroupeS1.cs,
//  NexusGroupeGotobi.cs) et dans le banc de parite (Tests\PariteGroupe) qui
//  rejoue 2016-2026 et compare chaque ordre a la recherche Python.
//
//  NxS1Logique     S1_NoiseAreaNQ (Python/S1_NoiseAreaNQ.py, reglage fige) :
//                  sigma 30 seances, controle toutes les 30 min, bande x1,2,
//                  VWAP, levier 2 % / vol 14 j plafonne a 4, sortie a la
//                  cloture (16:00, 13:00 les demi-seances).
//  NxGotobiLogique Gotobi 6J (Python/nexus/gotobi.py) : 08:00 vente, 09:55
//                  achat, 11:00 sortie (heure de Tokyo), jours gotobi.
//  Calendriers (feries et demi-seances NYSE, jours gotobi 2015-2035) generes
//  depuis le code Python valide : memes dates, a l identique.
//
//  Les heures recues sont en UTC ; les fuseaux de New York et Tokyo sont ceux
//  de Windows.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.Nexus
{
    public static class NxGroupeCalendrier
    {
        public static readonly TimeZoneInfo NewYork = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
        public static readonly TimeZoneInfo Tokyo = TimeZoneInfo.FindSystemTimeZoneById("Tokyo Standard Time");

        // genere depuis Python : REF.feries_nyse, demi_seance (nexus/live/strategies/s1.py), gotobi.jours_gotobi
        private static readonly int[] FeriesNyse = {
            20070102, 20121029, 20121030, 20150101, 20150119, 20150216, 20150403, 20150525, 20150703, 20150907, 20151126, 20151225,
            20160101, 20160118, 20160215, 20160325, 20160530, 20160704, 20160905, 20161124, 20161226, 20170102, 20170116, 20170220,
            20170414, 20170529, 20170704, 20170904, 20171123, 20171225, 20180101, 20180115, 20180219, 20180330, 20180528, 20180704,
            20180903, 20181122, 20181205, 20181225, 20190101, 20190121, 20190218, 20190419, 20190527, 20190704, 20190902, 20191128,
            20191225, 20200101, 20200120, 20200217, 20200410, 20200525, 20200703, 20200907, 20201126, 20201225, 20210101, 20210118,
            20210215, 20210402, 20210531, 20210705, 20210906, 20211125, 20211224, 20220101, 20220117, 20220221, 20220415, 20220530,
            20220620, 20220704, 20220905, 20221124, 20221226, 20230102, 20230116, 20230220, 20230407, 20230529, 20230619, 20230704,
            20230904, 20231123, 20231225, 20240101, 20240115, 20240219, 20240329, 20240527, 20240619, 20240704, 20240902, 20241128,
            20241225, 20250101, 20250109, 20250120, 20250217, 20250418, 20250526, 20250619, 20250704, 20250901, 20251127, 20251225,
            20260101, 20260119, 20260216, 20260403, 20260525, 20260619, 20260703, 20260907, 20261126, 20261225, 20270101, 20270118,
            20270215, 20270326, 20270531, 20270618, 20270705, 20270906, 20271125, 20271224, 20280101, 20280117, 20280221, 20280414,
            20280529, 20280619, 20280704, 20280904, 20281123, 20281225, 20290101, 20290115, 20290219, 20290330, 20290528, 20290619,
            20290704, 20290903, 20291122, 20291225, 20300101, 20300121, 20300218, 20300419, 20300527, 20300619, 20300704, 20300902,
            20301128, 20301225, 20310101, 20310120, 20310217, 20310411, 20310526, 20310619, 20310704, 20310901, 20311127, 20311225,
            20320101, 20320119, 20320216, 20320326, 20320531, 20320618, 20320705, 20320906, 20321125, 20321224, 20330101, 20330117,
            20330221, 20330415, 20330530, 20330620, 20330704, 20330905, 20331124, 20331226, 20340102, 20340116, 20340220, 20340407,
            20340529, 20340619, 20340704, 20340904, 20341123, 20341225, 20350101, 20350115, 20350219, 20350323, 20350528, 20350619,
            20350704, 20350903, 20351122, 20351225
        };
        private static readonly int[] DemiSeancesNyse = {
            20151127, 20151224, 20161125, 20170703, 20171124, 20180703, 20181123, 20181224, 20190703, 20191129, 20191224, 20201127,
            20201224, 20211126, 20221125, 20230703, 20231124, 20240703, 20241129, 20241224, 20250703, 20251128, 20251224, 20261127,
            20261224, 20271126, 20280703, 20281124, 20290703, 20291123, 20291224, 20300703, 20301129, 20301224, 20310703, 20311128,
            20311224, 20321126, 20331125, 20340703, 20341124, 20350703, 20351123, 20351224
        };
        private static readonly int[] JoursGotobi = {
            20150105, 20150109, 20150115, 20150120, 20150123, 20150130, 20150205, 20150210, 20150213, 20150220, 20150225, 20150227,
            20150305, 20150310, 20150313, 20150320, 20150325, 20150331, 20150403, 20150410, 20150415, 20150420, 20150424, 20150430,
            20150501, 20150508, 20150515, 20150520, 20150525, 20150529, 20150605, 20150610, 20150615, 20150619, 20150625, 20150630,
            20150703, 20150710, 20150715, 20150717, 20150724, 20150731, 20150805, 20150810, 20150814, 20150820, 20150825, 20150831,
            20150904, 20150910, 20150915, 20150918, 20150925, 20150930, 20151005, 20151009, 20151015, 20151020, 20151023, 20151030,
            20151105, 20151110, 20151113, 20151120, 20151125, 20151130, 20151204, 20151210, 20151215, 20151218, 20151225, 20151230,
            20160105, 20160108, 20160115, 20160120, 20160125, 20160129, 20160205, 20160210, 20160215, 20160219, 20160225, 20160229,
            20160304, 20160310, 20160315, 20160318, 20160325, 20160331, 20160405, 20160408, 20160415, 20160420, 20160425, 20160428,
            20160502, 20160510, 20160513, 20160520, 20160525, 20160531, 20160603, 20160610, 20160615, 20160620, 20160624, 20160630,
            20160705, 20160708, 20160715, 20160720, 20160725, 20160729, 20160805, 20160810, 20160815, 20160819, 20160825, 20160831,
            20160905, 20160909, 20160915, 20160920, 20160923, 20160930, 20161005, 20161007, 20161014, 20161020, 20161025, 20161031,
            20161104, 20161110, 20161115, 20161118, 20161125, 20161130, 20161205, 20161209, 20161215, 20161220, 20161222, 20161230,
            20170105, 20170110, 20170113, 20170120, 20170125, 20170131, 20170203, 20170210, 20170215, 20170220, 20170224, 20170228,
            20170303, 20170310, 20170315, 20170317, 20170324, 20170331, 20170405, 20170410, 20170414, 20170420, 20170425, 20170428,
            20170502, 20170510, 20170515, 20170519, 20170525, 20170531, 20170605, 20170609, 20170615, 20170620, 20170623, 20170630,
            20170705, 20170710, 20170714, 20170720, 20170725, 20170731, 20170804, 20170810, 20170815, 20170818, 20170825, 20170831,
            20170905, 20170908, 20170915, 20170920, 20170925, 20170929, 20171005, 20171010, 20171013, 20171020, 20171025, 20171031,
            20171102, 20171110, 20171115, 20171120, 20171124, 20171130, 20171205, 20171208, 20171215, 20171220, 20171225, 20171229,
            20180105, 20180110, 20180115, 20180119, 20180125, 20180131, 20180205, 20180209, 20180215, 20180220, 20180223, 20180228,
            20180305, 20180309, 20180315, 20180320, 20180323, 20180330, 20180405, 20180410, 20180413, 20180420, 20180425, 20180427,
            20180502, 20180510, 20180515, 20180518, 20180525, 20180531, 20180605, 20180608, 20180615, 20180620, 20180625, 20180629,
            20180705, 20180710, 20180713, 20180720, 20180725, 20180731, 20180803, 20180810, 20180815, 20180820, 20180824, 20180831,
            20180905, 20180910, 20180914, 20180920, 20180925, 20180928, 20181005, 20181010, 20181015, 20181019, 20181025, 20181031,
            20181105, 20181109, 20181115, 20181120, 20181122, 20181130, 20181205, 20181210, 20181214, 20181220, 20181225, 20181228,
            20190104, 20190110, 20190115, 20190118, 20190125, 20190131, 20190205, 20190208, 20190215, 20190220, 20190225, 20190228,
            20190305, 20190308, 20190315, 20190320, 20190325, 20190329, 20190405, 20190410, 20190415, 20190419, 20190425, 20190426,
            20190510, 20190515, 20190520, 20190524, 20190531, 20190605, 20190610, 20190614, 20190620, 20190625, 20190628, 20190705,
            20190710, 20190712, 20190719, 20190725, 20190731, 20190805, 20190809, 20190815, 20190820, 20190823, 20190830, 20190905,
            20190910, 20190913, 20190920, 20190925, 20190930, 20191004, 20191010, 20191015, 20191018, 20191025, 20191031, 20191105,
            20191108, 20191115, 20191120, 20191125, 20191129, 20191205, 20191210, 20191213, 20191220, 20191225, 20191230, 20200110,
            20200115, 20200120, 20200124, 20200131, 20200205, 20200210, 20200214, 20200220, 20200225, 20200228, 20200305, 20200310,
            20200313, 20200319, 20200325, 20200331, 20200403, 20200410, 20200415, 20200420, 20200424, 20200430, 20200501, 20200508,
            20200515, 20200520, 20200525, 20200529, 20200605, 20200610, 20200615, 20200619, 20200625, 20200630, 20200703, 20200710,
            20200715, 20200720, 20200722, 20200731, 20200805, 20200807, 20200814, 20200820, 20200825, 20200831, 20200904, 20200910,
            20200915, 20200918, 20200925, 20200930, 20201005, 20201009, 20201015, 20201020, 20201023, 20201030, 20201105, 20201110,
            20201113, 20201120, 20201125, 20201130, 20201204, 20201210, 20201215, 20201218, 20201225, 20201230, 20210105, 20210108,
            20210115, 20210120, 20210125, 20210129, 20210205, 20210210, 20210215, 20210219, 20210225, 20210226, 20210305, 20210310,
            20210315, 20210319, 20210325, 20210331, 20210405, 20210409, 20210415, 20210420, 20210423, 20210430, 20210510, 20210514,
            20210520, 20210525, 20210531, 20210604, 20210610, 20210615, 20210618, 20210625, 20210630, 20210705, 20210709, 20210715,
            20210720, 20210721, 20210730, 20210805, 20210810, 20210813, 20210820, 20210825, 20210831, 20210903, 20210910, 20210915,
            20210917, 20210924, 20210930, 20211005, 20211008, 20211015, 20211020, 20211025, 20211029, 20211105, 20211110, 20211115,
            20211119, 20211125, 20211130, 20211203, 20211210, 20211215, 20211220, 20211224, 20211230, 20220105, 20220107, 20220114,
            20220120, 20220125, 20220131, 20220204, 20220210, 20220215, 20220218, 20220225, 20220228, 20220304, 20220310, 20220315,
            20220318, 20220325, 20220331, 20220405, 20220408, 20220415, 20220420, 20220425, 20220428, 20220502, 20220510, 20220513,
            20220520, 20220525, 20220531, 20220603, 20220610, 20220615, 20220620, 20220624, 20220630, 20220705, 20220708, 20220715,
            20220720, 20220725, 20220729, 20220805, 20220810, 20220815, 20220819, 20220825, 20220831, 20220905, 20220909, 20220915,
            20220920, 20220922, 20220930, 20221005, 20221007, 20221014, 20221020, 20221025, 20221031, 20221104, 20221110, 20221115,
            20221118, 20221125, 20221130, 20221205, 20221209, 20221215, 20221220, 20221223, 20221230, 20230105, 20230110, 20230113,
            20230120, 20230125, 20230131, 20230203, 20230210, 20230215, 20230220, 20230224, 20230228, 20230303, 20230310, 20230315,
            20230320, 20230324, 20230331, 20230405, 20230410, 20230414, 20230420, 20230425, 20230428, 20230502, 20230510, 20230515,
            20230519, 20230525, 20230531, 20230605, 20230609, 20230615, 20230620, 20230623, 20230630, 20230705, 20230710, 20230714,
            20230720, 20230725, 20230731, 20230804, 20230810, 20230815, 20230818, 20230825, 20230831, 20230905, 20230908, 20230915,
            20230920, 20230925, 20230929, 20231005, 20231010, 20231013, 20231020, 20231025, 20231031, 20231102, 20231110, 20231115,
            20231120, 20231124, 20231130, 20231205, 20231208, 20231215, 20231220, 20231225, 20231229, 20240105, 20240110, 20240115,
            20240119, 20240125, 20240131, 20240205, 20240209, 20240215, 20240220, 20240222, 20240229, 20240305, 20240308, 20240315,
            20240319, 20240325, 20240329, 20240405, 20240410, 20240415, 20240419, 20240425, 20240430, 20240502, 20240510, 20240515,
            20240520, 20240524, 20240531, 20240605, 20240610, 20240614, 20240620, 20240625, 20240628, 20240705, 20240710, 20240712,
            20240719, 20240725, 20240731, 20240805, 20240809, 20240815, 20240820, 20240823, 20240830, 20240905, 20240910, 20240913,
            20240920, 20240925, 20240930, 20241004, 20241010, 20241015, 20241018, 20241025, 20241031, 20241105, 20241108, 20241115,
            20241120, 20241125, 20241129, 20241205, 20241210, 20241213, 20241220, 20241225, 20241230, 20250110, 20250115, 20250120,
            20250124, 20250131, 20250205, 20250210, 20250214, 20250220, 20250225, 20250228, 20250305, 20250310, 20250314, 20250319,
            20250325, 20250331, 20250404, 20250410, 20250415, 20250418, 20250425, 20250430, 20250502, 20250509, 20250515, 20250520,
            20250523, 20250530, 20250605, 20250610, 20250613, 20250620, 20250625, 20250630, 20250704, 20250710, 20250715, 20250718,
            20250725, 20250731, 20250805, 20250808, 20250815, 20250820, 20250825, 20250829, 20250905, 20250910, 20250912, 20250919,
            20250925, 20250930, 20251003, 20251010, 20251015, 20251020, 20251024, 20251031, 20251105, 20251110, 20251114, 20251120,
            20251125, 20251128, 20251205, 20251210, 20251215, 20251219, 20251225, 20251230, 20260105, 20260109, 20260115, 20260120,
            20260123, 20260130, 20260205, 20260210, 20260213, 20260220, 20260225, 20260227, 20260305, 20260310, 20260313, 20260319,
            20260325, 20260331, 20260403, 20260410, 20260415, 20260420, 20260424, 20260430, 20260501, 20260508, 20260515, 20260520,
            20260525, 20260529, 20260605, 20260610, 20260615, 20260619, 20260625, 20260630, 20260703, 20260710, 20260715, 20260717,
            20260724, 20260731, 20260805, 20260810, 20260814, 20260820, 20260825, 20260831, 20260904, 20260910, 20260915, 20260918,
            20260925, 20260930, 20261005, 20261009, 20261015, 20261020, 20261023, 20261030, 20261105, 20261110, 20261113, 20261120,
            20261125, 20261130, 20261204, 20261210, 20261215, 20261218, 20261225, 20261230, 20270105, 20270108, 20270115, 20270120,
            20270125, 20270129, 20270205, 20270210, 20270215, 20270219, 20270225, 20270226, 20270305, 20270310, 20270315, 20270319,
            20270325, 20270331, 20270405, 20270409, 20270415, 20270420, 20270423, 20270430, 20270510, 20270514, 20270520, 20270525,
            20270531, 20270604, 20270610, 20270615, 20270618, 20270625, 20270630, 20270705, 20270709, 20270715, 20270720, 20270723,
            20270730, 20270805, 20270810, 20270813, 20270820, 20270825, 20270831, 20270903, 20270910, 20270915, 20270917, 20270924,
            20270930, 20271005, 20271008, 20271015, 20271020, 20271025, 20271029, 20271105, 20271110, 20271115, 20271119, 20271125,
            20271130, 20271203, 20271210, 20271215, 20271220, 20271224, 20271230, 20280105, 20280107, 20280114, 20280120, 20280125,
            20280131, 20280204, 20280210, 20280215, 20280218, 20280225, 20280229, 20280303, 20280310, 20280315, 20280317, 20280324,
            20280331, 20280405, 20280410, 20280414, 20280420, 20280425, 20280428, 20280502, 20280510, 20280515, 20280519, 20280525,
            20280531, 20280605, 20280609, 20280615, 20280620, 20280623, 20280630, 20280705, 20280710, 20280714, 20280720, 20280725,
            20280731, 20280804, 20280810, 20280815, 20280818, 20280825, 20280831, 20280905, 20280908, 20280915, 20280920, 20280925,
            20280929, 20281005, 20281010, 20281013, 20281020, 20281025, 20281031, 20281102, 20281110, 20281115, 20281120, 20281124,
            20281130, 20281205, 20281208, 20281215, 20281220, 20281225, 20281229, 20290105, 20290110, 20290115, 20290119, 20290125,
            20290131, 20290205, 20290209, 20290215, 20290220, 20290222, 20290228, 20290305, 20290309, 20290315, 20290319, 20290323,
            20290330, 20290405, 20290410, 20290413, 20290420, 20290425, 20290427, 20290502, 20290510, 20290515, 20290518, 20290525,
            20290531, 20290605, 20290608, 20290615, 20290620, 20290625, 20290629, 20290705, 20290710, 20290713, 20290720, 20290725,
            20290731, 20290803, 20290810, 20290815, 20290820, 20290824, 20290831, 20290905, 20290910, 20290914, 20290920, 20290925,
            20290928, 20291005, 20291010, 20291015, 20291019, 20291025, 20291031, 20291105, 20291109, 20291115, 20291120, 20291122,
            20291130, 20291205, 20291210, 20291214, 20291220, 20291225, 20291228, 20300104, 20300110, 20300115, 20300118, 20300125,
            20300131, 20300205, 20300208, 20300215, 20300220, 20300225, 20300228, 20300305, 20300308, 20300315, 20300319, 20300325,
            20300329, 20300405, 20300410, 20300415, 20300419, 20300425, 20300430, 20300502, 20300510, 20300515, 20300520, 20300524,
            20300531, 20300605, 20300610, 20300614, 20300620, 20300625, 20300628, 20300705, 20300710, 20300712, 20300719, 20300725,
            20300731, 20300805, 20300809, 20300815, 20300820, 20300823, 20300830, 20300905, 20300910, 20300913, 20300920, 20300925,
            20300930, 20301004, 20301010, 20301015, 20301018, 20301025, 20301031, 20301105, 20301108, 20301115, 20301120, 20301125,
            20301129, 20301205, 20301210, 20301213, 20301220, 20301225, 20301230, 20310110, 20310115, 20310120, 20310124, 20310131,
            20310205, 20310210, 20310214, 20310220, 20310225, 20310228, 20310305, 20310310, 20310314, 20310320, 20310325, 20310331,
            20310404, 20310410, 20310415, 20310418, 20310425, 20310430, 20310502, 20310509, 20310515, 20310520, 20310523, 20310530,
            20310605, 20310610, 20310613, 20310620, 20310625, 20310630, 20310704, 20310710, 20310715, 20310718, 20310725, 20310731,
            20310805, 20310808, 20310815, 20310820, 20310825, 20310829, 20310905, 20310910, 20310912, 20310919, 20310925, 20310930,
            20311003, 20311010, 20311015, 20311020, 20311024, 20311031, 20311105, 20311110, 20311114, 20311120, 20311125, 20311128,
            20311205, 20311210, 20311215, 20311219, 20311225, 20311230, 20320105, 20320109, 20320115, 20320120, 20320123, 20320130,
            20320205, 20320210, 20320213, 20320220, 20320225, 20320227, 20320305, 20320310, 20320315, 20320319, 20320325, 20320331,
            20320405, 20320409, 20320415, 20320420, 20320423, 20320430, 20320510, 20320514, 20320520, 20320525, 20320531, 20320604,
            20320610, 20320615, 20320618, 20320625, 20320630, 20320705, 20320709, 20320715, 20320720, 20320723, 20320730, 20320805,
            20320810, 20320813, 20320820, 20320825, 20320831, 20320903, 20320910, 20320915, 20320917, 20320924, 20320930, 20321005,
            20321008, 20321015, 20321020, 20321025, 20321029, 20321105, 20321110, 20321115, 20321119, 20321125, 20321130, 20321203,
            20321210, 20321215, 20321220, 20321224, 20321230, 20330105, 20330107, 20330114, 20330120, 20330125, 20330131, 20330204,
            20330210, 20330215, 20330218, 20330225, 20330228, 20330304, 20330310, 20330315, 20330318, 20330325, 20330331, 20330405,
            20330408, 20330415, 20330420, 20330425, 20330428, 20330502, 20330510, 20330513, 20330520, 20330525, 20330531, 20330603,
            20330610, 20330615, 20330620, 20330624, 20330630, 20330705, 20330708, 20330715, 20330720, 20330725, 20330729, 20330805,
            20330810, 20330815, 20330819, 20330825, 20330831, 20330905, 20330909, 20330915, 20330920, 20330922, 20330930, 20331005,
            20331007, 20331014, 20331020, 20331025, 20331031, 20331104, 20331110, 20331115, 20331118, 20331125, 20331130, 20331205,
            20331209, 20331215, 20331220, 20331223, 20331230, 20340105, 20340110, 20340113, 20340120, 20340125, 20340131, 20340203,
            20340210, 20340215, 20340220, 20340224, 20340228, 20340303, 20340310, 20340315, 20340317, 20340324, 20340331, 20340405,
            20340410, 20340414, 20340420, 20340425, 20340428, 20340502, 20340510, 20340515, 20340519, 20340525, 20340531, 20340605,
            20340609, 20340615, 20340620, 20340623, 20340630, 20340705, 20340710, 20340714, 20340720, 20340725, 20340731, 20340804,
            20340810, 20340815, 20340818, 20340825, 20340831, 20340905, 20340908, 20340915, 20340920, 20340925, 20340929, 20341005,
            20341010, 20341013, 20341020, 20341025, 20341031, 20341102, 20341110, 20341115, 20341120, 20341124, 20341130, 20341205,
            20341208, 20341215, 20341220, 20341225, 20341229, 20350105, 20350110, 20350115, 20350119, 20350125, 20350131, 20350205,
            20350209, 20350215, 20350220, 20350222, 20350228, 20350305, 20350309, 20350315, 20350320, 20350323, 20350330, 20350405,
            20350410, 20350413, 20350420, 20350425, 20350427, 20350502, 20350510, 20350515, 20350518, 20350525, 20350531, 20350605,
            20350608, 20350615, 20350620, 20350625, 20350629, 20350705, 20350710, 20350713, 20350720, 20350725, 20350731, 20350803,
            20350810, 20350815, 20350820, 20350824, 20350831, 20350905, 20350910, 20350914, 20350920, 20350925, 20350928, 20351005,
            20351010, 20351015, 20351019, 20351025, 20351031, 20351105, 20351109, 20351115, 20351120, 20351122, 20351130, 20351205,
            20351210, 20351214, 20351220, 20351225, 20351228
        };
        private static readonly HashSet<int> feries = new HashSet<int>(FeriesNyse);
        private static readonly HashSet<int> demi = new HashSet<int>(DemiSeancesNyse);
        private static readonly HashSet<int> gotobi = new HashSet<int>(JoursGotobi);

        public static int Cle(DateTime d) { return d.Year * 10000 + d.Month * 100 + d.Day; }
        public static bool FerieNyse(DateTime d) { return feries.Contains(Cle(d)); }
        public static bool DemiSeance(DateTime d) { return demi.Contains(Cle(d)); }
        public static bool JourGotobi(DateTime d) { return gotobi.Contains(Cle(d)); }

        public static IEnumerable<DateTime> ProchainsGotobi(DateTime depuis, int n)
        {
            int k = Cle(depuis);
            return JoursGotobi.Where(x => x >= k).Take(n).Select(x => new DateTime(x / 10000, x / 100 % 100, x % 100));
        }

        public static DateTime VersNewYork(DateTime utc) { return TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), NewYork); }
        public static DateTime VersTokyo(DateTime utc) { return TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), Tokyo); }
        public static DateTime TokyoVersUtc(DateTime tokyo) { return TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(tokyo, DateTimeKind.Unspecified), Tokyo); }
    }

    /// <summary>Sommes au bit pres comme numpy (somme par paires : 8 accumulateurs jusqu a 128 valeurs).</summary>
    public static class NxNumpy
    {
        public static double Somme(IList<double> a)
        {
            int n = a.Count;
            if (n < 8)
            {
                double s = 0.0;
                for (int i = 0; i < n; i++) s += a[i];
                return s;
            }
            if (n > 128) throw new ArgumentException("NxNumpy.Somme : au plus 128 valeurs");
            double r0 = a[0], r1 = a[1], r2 = a[2], r3 = a[3], r4 = a[4], r5 = a[5], r6 = a[6], r7 = a[7];
            int k = 8;
            for (; k < n - (n % 8); k += 8)
            {
                r0 += a[k]; r1 += a[k + 1]; r2 += a[k + 2]; r3 += a[k + 3];
                r4 += a[k + 4]; r5 += a[k + 5]; r6 += a[k + 6]; r7 += a[k + 7];
            }
            double res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7));
            for (; k < n; k++) res += a[k];
            return res;
        }

        public static double Moyenne(IList<double> a) { return Somme(a) / a.Count; }

        public static double EcartType(IList<double> a, int ddof)
        {
            double m = Moyenne(a);
            double[] d2 = a.Select(x => (x - m) * (x - m)).ToArray();
            return Math.Sqrt(Somme(d2) / (a.Count - ddof));
        }
    }

    /// <summary>Decision d une strategie : position cible (signee) et motif.</summary>
    public class NxDecision
    {
        public int Cible;
        public string Motif = "";
        public NxDecision(int cible, string motif) { Cible = cible; Motif = motif; }
    }

    // =========================================================================
    //  S1 : Noise Area Intraday Momentum sur NQ
    // =========================================================================
    public class NxS1Logique
    {
        public const int SigmaSeances = 30, ControleMin = 30, VolSeances = 14, Ouverture = 570;
        public const double Bande = 1.2, VolCible = 0.02, LevierMax = 4.0;

        public double Capital = 100000;                 // capital du jour (fixe, ou fourni par la strategie)
        public double ValeurPoint = 2.0;                // instrument negocie (MNQ : 2 $, NQ : 20 $)
        public Func<DateTime, double> CapitalDuJour;    // optionnel (banc de parite : equity de la recherche)

        private readonly List<double[]> ecarts = new List<double[]>();
        private readonly List<double> clotures = new List<double>();
        private DateTime jour = DateTime.MinValue;
        private bool valide, termine, pret;
        private int fin, prochain, mDernier;
        private List<int> controles = new List<int>();
        private double[] C = new double[391], sigma = new double[391];
        private double pv, vol, ouv, closeCourant, haut, bas, levier = double.NaN;

        public int Cible { get; private set; }
        public int Contrats { get; private set; }
        public bool Pret { get { return pret; } }
        public double Levier { get { return levier; } }
        public double Haut { get { return haut; } }
        public double Bas { get { return bas; } }
        public DateTime Jour { get { return jour; } }
        public int Fin { get { return fin; } }
        public int SeancesHistorique { get { return ecarts.Count; } }

        /// <summary>Barre 1 minute de NQ close (fin de barre en UTC) -> decisions (dans l ordre), vide si rien ne change.</summary>
        public List<NxDecision> SurBarre(DateTime finUtc, double o, double h, double l, double c, double v)
        {
            List<NxDecision> res = new List<NxDecision>();
            DateTime n = NxGroupeCalendrier.VersNewYork(finUtc);
            int m = n.Hour * 60 + n.Minute - Ouverture;
            if (m < 1 || m > 390 || n.DayOfWeek == DayOfWeek.Saturday || n.DayOfWeek == DayOfWeek.Sunday) return res;
            DateTime d = n.Date;
            if (d != jour)
            {
                FinManquee(res);
                NouvelleSeance(d, m, o);
            }
            if (!valide || termine || m <= mDernier) return res;
            while (pret && prochain < controles.Count && controles[prochain] < m)
            {
                Controle(controles[prochain], res);
                prochain++;
            }
            if (fin < m)
            {
                Clore(res);
                return res;
            }
            C[m] = c;
            closeCourant = c;
            pv += (h + l + c) / 3.0 * v;
            vol += v;
            mDernier = m;
            if (pret && prochain < controles.Count && controles[prochain] == m)
            {
                Controle(m, res);
                prochain++;
            }
            if (m == fin) Clore(res);
            return res;
        }

        /// <summary>Horloge (heure du fil de donnees, UTC) : sortie si la barre de cloture n arrive pas.</summary>
        public List<NxDecision> SurHorloge(DateTime utc)
        {
            List<NxDecision> res = new List<NxDecision>();
            if (jour == DateTime.MinValue || !valide || termine) return res;
            DateTime n = NxGroupeCalendrier.VersNewYork(utc);
            if (n.Date != jour || (n.Hour * 60 + n.Minute - Ouverture) * 60 + n.Second >= fin * 60 + 10) FinManquee(res);
            return res;
        }

        private void NouvelleSeance(DateTime d, int m, double o)
        {
            jour = d;
            valide = d.DayOfWeek != DayOfWeek.Saturday && d.DayOfWeek != DayOfWeek.Sunday && !NxGroupeCalendrier.FerieNyse(d) && m <= 5;
            fin = NxGroupeCalendrier.DemiSeance(d) ? 210 : 390;
            controles = new List<int>();
            for (int k = ControleMin; k < fin; k += ControleMin) controles.Add(k);
            prochain = 0;
            C = Enumerable.Repeat(double.NaN, 391).ToArray();
            mDernier = 0;
            pv = 0;
            vol = 0;
            ouv = o;
            closeCourant = o;
            termine = false;
            Cible = 0;
            pret = false;
            Contrats = 0;
            if (!valide) return;
            double veille = clotures.Count > 0 ? clotures[clotures.Count - 1] : double.NaN;
            double vj = double.NaN;
            if (clotures.Count >= VolSeances + 1)
            {
                double[] r = new double[VolSeances];
                for (int k = 0; k < VolSeances; k++)
                {
                    int i = clotures.Count - VolSeances + k;
                    r[k] = clotures[i] / clotures[i - 1] - 1;
                }
                vj = NxNumpy.EcartType(r, 1);
            }
            levier = vj > 0 && !double.IsNaN(vj) ? Math.Min(VolCible / vj, LevierMax) : double.NaN;
            sigma = CalculerSigma();
            haut = Math.Max(ouv, veille);
            bas = Math.Min(ouv, veille);
            pret = !double.IsNaN(levier) && !double.IsNaN(veille) && controles.All(k => !double.IsNaN(sigma[k]));
            if (pret)
            {
                double cap = CapitalDuJour != null ? CapitalDuJour(d) : Capital;
                Contrats = (int)Math.Floor(cap * levier / (ouv * ValeurPoint) + 0.5);
            }
        }

        private double[] CalculerSigma()
        {
            double[] s = Enumerable.Repeat(double.NaN, 391).ToArray();
            for (int m = 1; m <= 390; m++)
            {
                List<double> v = new List<double>(SigmaSeances);
                for (int i = ecarts.Count - 1; i >= 0 && v.Count < SigmaSeances; i--)
                    if (!double.IsNaN(ecarts[i][m])) v.Add(ecarts[i][m]);
                if (v.Count == SigmaSeances)
                {
                    v.Reverse();                                    // ordre chronologique, sommation numpy
                    s[m] = NxNumpy.Moyenne(v);
                }
            }
            return s;
        }

        private void Controle(int k, List<NxDecision> res)
        {
            double c = closeCourant;
            double vw = vol > 0 ? pv / vol : double.NaN;
            double s = sigma[k];
            double up = haut * (1 + Bande * s), lo = bas * (1 - Bande * s);
            int cible = (c > up && c > vw) ? Contrats : ((c < lo && c < vw) ? -Contrats : 0);
            if (cible != Cible)
                res.Add(new NxDecision(cible, string.Format(CultureInfo.InvariantCulture, "controle {0}:{1:00} close {2:0.00} bande [{3:0.00} ; {4:0.00}] VWAP {5:0.00}",
                                                             (Ouverture + k) / 60, (Ouverture + k) % 60, c, lo, up, vw)));
            Cible = cible;
        }

        private void Clore(List<NxDecision> res)
        {
            termine = true;
            if (Cible != 0) res.Add(new NxDecision(0, "fin de seance"));
            Cible = 0;
            double[] e = new double[391];
            double dernier = ouv;
            for (int m = 0; m <= 390; m++)
            {
                if (m == 0 || m > fin) { e[m] = double.NaN; continue; }
                if (!double.IsNaN(C[m])) dernier = C[m];
                e[m] = Math.Abs(dernier / ouv - 1);
            }
            ecarts.Add(e);
            if (ecarts.Count > SigmaSeances + 40) ecarts.RemoveAt(0);
            double cl = !double.IsNaN(C[fin]) ? C[fin] : dernier;
            clotures.Add(cl);
            if (clotures.Count > VolSeances + 2) clotures.RemoveAt(0);
        }

        private void FinManquee(List<NxDecision> res)
        {
            if (jour == DateTime.MinValue || !valide || termine) return;
            if (mDernier >= fin - 4) { Clore(res); return; }
            termine = true;
            if (Cible != 0) res.Add(new NxDecision(0, "seance incomplete : sortie"));
            Cible = 0;
        }
    }

    // =========================================================================
    //  Gotobi : yen (6J) autour du fixing de Tokyo
    // =========================================================================
    public class NxGotobiLogique
    {
        public double Capital = 100000, Exposition = 0.95, ValeurPoint = 12500000;
        public int ContratsFixes;                       // > 0 : taille fixe
        public int ToleranceMin = 10;
        public TimeSpan Entree = new TimeSpan(8, 0, 0), Fixing = new TimeSpan(9, 55, 0), Sortie = new TimeSpan(11, 0, 0);

        private DateTime jour = DateTime.MinValue;
        private readonly HashSet<string> faits = new HashSet<string>();
        public int Cible { get; private set; }
        public int Contrats { get; private set; }
        public DateTime JourTokyo { get { return jour; } }
        public bool JourGotobi { get { return jour != DateTime.MinValue && NxGroupeCalendrier.JourGotobi(jour); } }
        public IEnumerable<string> JambesFaites { get { return faits.OrderBy(x => x); } }

        public int Taille(double dernierPrix)
        {
            if (ContratsFixes > 0) return ContratsFixes;
            if (!(dernierPrix > 0)) return 0;
            return (int)Math.Round(Capital * Exposition / (dernierPrix * ValeurPoint), MidpointRounding.ToEven);
        }

        /// <summary>Instant du fil de donnees (UTC) : debut de la barre qui commence, ou horloge. -> decisions.</summary>
        public List<NxDecision> SurInstant(DateTime utc, double dernierPrix)
        {
            List<NxDecision> res = new List<NxDecision>();
            DateTime n = NxGroupeCalendrier.VersTokyo(utc);
            DateTime d = n.Date;
            if (d != jour)
            {
                jour = d;
                faits.Clear();
                Contrats = 0;
            }
            if (!NxGroupeCalendrier.JourGotobi(d))
            {
                if (Cible != 0) Poser(0, "jour non gotobi : securite", res);
                return res;
            }
            foreach (string jambe in new[] { "entree", "fixing", "sortie" })
            {
                if (faits.Contains(jambe)) continue;
                DateTime h = d + (jambe == "entree" ? Entree : jambe == "fixing" ? Fixing : Sortie);
                if (n < h) continue;
                faits.Add(jambe);
                if (jambe == "sortie")
                {
                    if (Cible != 0) Poser(0, "11:00 Tokyo : sortie", res);
                    continue;
                }
                if (n > h.AddMinutes(ToleranceMin))
                {
                    if (jambe == "fixing" && Cible != 0) Poser(0, "retournement manque : a plat", res);
                    continue;
                }
                if (Contrats == 0 || jambe == "entree") Contrats = Taille(dernierPrix);
                if (Contrats <= 0) continue;
                if (jambe == "entree") Poser(-Contrats, "08:00 Tokyo : vente avant le fixing", res);
                else Poser(Contrats, "09:55 Tokyo : achat apres le fixing", res);
            }
            return res;
        }

        private void Poser(int q, string motif, List<NxDecision> res)
        {
            Cible = q;
            res.Add(new NxDecision(q, motif));
        }
    }
}
