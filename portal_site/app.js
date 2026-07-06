const menuToggle = document.getElementById("menuToggle");
const mainNav = document.getElementById("mainNav");
const backTop = document.getElementById("backTop");
const contactForm = document.getElementById("contactForm");
const formNote = document.getElementById("formNote");
const langButtons = document.querySelectorAll(".lang-switch button");

const translations = {
  ja: {
    langTag: "ja",
    pageTitle: "Kizuna - 公式サイト",
    brand: "Kizuna",
    navMission: "製品を見る",
    navApproach: "アプローチ",
    navLabs: "Kizuna Labs",
    navStories: "ストーリー",
    navCareers: "採用情報",
    navPress: "プレス",
    navContact: "ダウンロード",
    menuToggle: "メニューを開く",
    ctaPrimary: "ダウンロード",
    heroEyebrow: "在日華人向けの社交・恋活アプリ",
    heroTitle: "最後の“初デート”へ。",
    heroSlogan:
      "一般的な恋愛アプリとはまったく別次元。最高の体験を。",
    heroSubtitle:
      "Kizuna は在日華人のためのローカルマッチング、短動画、映画、ライブ体験を安全に届けます。",
    heroPrimary: "アプリをダウンロード",
    heroSecondary: "仕組みを見る",
    heroDeviceTitle: "Kizuna Social",
    heroDeviceChip1: "同城デート",
    heroDeviceChip2: "短動画",
    heroDeviceChip3: "映画",
    heroDeviceChip4: "ライブ",
    missionKicker: "Our Approach",
    missionTitle: "ここから最初のデートを始めよう",
    missionCopy1:
      "Kizuna は、真剣に関係を探す人は誰でも、相性の良い人に出会う価値があると信じています。",
    missionCopy2:
      "私たちはアプリに留めるためではなく、本当に大切な出会いへ導くために存在します。",
    missionCopy3:
      "選択肢が多すぎる時代だからこそ、少なく、でもより正確に。数ではなく質の出会いを。",
    missionDesc:
      "Kizuna はスワイプを終わらせ、会いたい人と出会うために設計されています。",
    missionBody:
      "本人確認、同城マッチ、興味プロフィールで自然なつながりを生み出します。",
    missionBtn: "詳しく見る",
    missionLink: "仕組みを見る →",
    missionPageKicker: "At the heart of Kizuna",
    missionPageTitle: "より孤独の少ない世界をつくる",
    missionPageLead: "親密でリアルなつながりを生み出すために。",
    missionPageValuesTitle: "Kizuna、内容で距離を近づけ、出会いで孤独を終わらせる。",
    missionPageValuesDesc:
      "正しい出会いだけでなく、無限のコンテンツもあります。",
    missionPageValuesBody:
      "",
    missionPageValue1Title: "同城デート",
    missionPageValue1Desc:
      "あなたの街で、会いたい人に出会う。",
    missionPageValue2Title: "精彩短视频",
    missionPageValue2Desc:
      "日常をシェアして、あなたの魅力を見せましょう。",
    missionPageValue3Title: "海量影视",
    missionPageValue3Desc:
      "3万本以上の動画が見放題。豊富な映像を好きなだけ。",
    missionPageValue4Title: "美女直播",
    missionPageValue4Desc:
      "高颜值主播都在这里等你来聊。",
    missionPageApproachTitle: "実は、私たちはあなたをもっと理解しています。",
    missionPageApproachDesc:
      "信頼できる本人確認と同城マッチで出会いを支えます。",
    missionPageApproach1Title: "詳細プロフィール",
    missionPageApproach1Desc: "本当の自分を伝えられる設計。",
    missionPageApproach2Title: "質の高い会話",
    missionPageApproach2Desc: "興味から自然に会話が始まります。",
    missionPageApproach3Title: "スマートマッチ",
    missionPageApproach3Desc: "行動データで精度を高めます。",
    missionPageBack: "トップへ戻る",
    missionPageInsightsTitle: "アプリの特徴",
    missionPageInsight1Title: "詳細プロフィール",
    missionPageInsight1Desc: "リアルな生活を見せて信頼を築く。",
    missionPageInsight2Title: "効果的なプロンプト",
    missionPageInsight2Desc: "自然な会話を引き出す。",
    missionPageInsight3Title: "会話のきっかけ",
    missionPageInsight3Desc: "細部へのいいねで話が始まる。",
    missionPageInsight4Title: "マッチングアルゴリズム",
    missionPageInsight4Desc: "好みを理解して精度を上げる。",
    missionPageInsight5Title: "意味のあるいいね",
    missionPageInsight5Desc: "少なく、でも的確に。",
    missionPageInsight6Title: "透明ないいね",
    missionPageInsight6Desc: "誰が好きかを見せる。",
    missionPageInsight7Title: "返信リマインド",
    missionPageInsight7Desc: "やり取りの機会を逃さない。",
    missionPageInsight8Title: "スマートマッチ",
    missionPageInsight8Desc: "フィードバックで最適化。",
    approachKicker: "Product",
    approachTitle: "出会いを、もっとリアルに",
    approachDesc:
      "同城での出会いからリアルタイムの交流まで、私たちはリアルさと効率のためにソーシャル体験を再設計します。",
    approachCard1Title: "真人動画認証",
    approachCard1Desc: "本人が動画で認証を完了。",
    approachCard2Title: "位置情報の厳格検証",
    approachCard2Desc: "実際の位置に基づき、虚偽を排除。",
    approachCard3Title: "公式身元審査",
    approachCard3Desc: "多重審査で偽アカウントを低減。",
    approachCard4Title: "実在行動メカニズム",
    approachCard4Desc: "チャット・交流・マッチを不正対策で守る。",
    labsKicker: "",
    labsTitle: "Kizunaで出会う",
    labsDesc:
      "気まずい対面デートにさようなら。私たちの独身コミュニティに参加して、好きな人を見つけましょう。",
    labsLink: "ユーザーの声 →",
    storiesKicker: "Stories",
    storiesTitle: "ユーザーの声",
    story1Quote:
      "「Kizuna で本当に価値観が合う人に出会えました。」",
    story1Author: "— Haruka · 東京",
    story2Quote:
      "「短動画で自然に会話が始まりました。」",
    story2Author: "— Leo · 大阪",
    story3Quote:
      "「本人確認とプライバシーが安心でした。」",
    story3Author: "— Lan · 名古屋",
    careersKicker: "Work at Kizuna",
    careersTitle: "一緒に働きませんか",
    careersDesc:
      "私たちは、より楽しい出会いを通して、あなたの毎日をもっと輝かせたいと考えています。",
    careersBtn: "参加する",
    careersPageKicker: "Careers",
    careersPageTitle: "より多くの人が運命の相手に出会えるように。",
    careersPageLead:
      "人間らしく、効果的な出会いを実現するプロダクトを一緒につくりましょう。",
    careersPageCta: "募集を見る",
    careersValueKicker: "Diversity & Inclusion",
    careersValueTitle: "多様性がイノベーションを生む。",
    careersValueLead:
      "多様な背景や考え方を持つ人々が成功をつくると信じています。",
    careersValue1Title: "輪を広げる",
    careersValue1Desc: "誰もが歓迎される環境をつくります。",
    careersValue2Title: "愛をもって向き合う",
    careersValue2Desc: "率直さと敬意を大切にします。",
    careersValue3Title: "未知を知る",
    careersValue3Desc: "学び続け、成長し続けます。",
    careersStatsKicker: "市場ポテンシャル",
    careersStatsTitle: "市場ポテンシャル",
    careersStat1Value: "42%",
    careersStat1Label: "主要年齢層の独身比率",
    careersStat2Value: "78%",
    careersStat2Label: "オンライン交流の利用意向",
    careersStat3Value: "65%",
    careersStat3Label: "モバイル利用の頻度",
    careersPerkKicker: "Perks & Benefits",
    careersPerkTitle: "最高の仕事と最高の生活を。",
    careersPerk1: "ハイブリッド & リモート対応",
    careersPerk2: "充実した医療サポート",
    careersPerk3: "十分な休暇とウェルネス休暇",
    careersPerk4: "学習支援の補助",
    careersPerk5: "育児・家族サポート",
    careersPerk6: "コミュニティ支援制度",
    careersOpenKicker: "Openings",
    careersOpenTitle: "募集中です。",
    careersOpenLead:
      "ミッションに共感する方をお待ちしています。",
    careersGroup1Title: "エンジニア",
    careersGroup1Count: "（11）",
    careersGroup1Desc:
      "小さな改善を積み重ねて体験を磨き込みます。",
    careersGroup2Title: "マーケティング",
    careersGroup2Count: "（04）",
    careersGroup2Desc:
      "ブランドとコミュニティをつなぐ仕事です。",
    careersGroup3Title: "プロダクト",
    careersGroup3Count: "（07）",
    careersGroup3Desc:
      "新機能の設計から体験改善まで担当します。",
    careersRole1: "Android エンジニア  東京",
    careersRole2: "iOS エンジニア  東京",
    careersRole3: "機械学習エンジニア（成果）  東京",
    careersRole4: "シニアデータエンジニア  東京",
    careersRole5: "プラットフォームEM  東京",
    careersRole6: "シニア iOS エンジニア  東京",
    careersRole7: "ブランド戦略ディレクター  東京",
    careersRole8: "PR ディレクター  東京",
    careersRole9: "編集ディレクター  東京",
    careersRole10: "プロダクトマーケ担当  東京",
    careersRole11: "リードデザイナー（成果）  東京",
    careersRole12: "リードPM（成果）  東京",
    careersRole13: "リードPM（アカウント健全性）  東京",
    careersRole14: "リードデザイナー（Trust & Safety）  東京",
    careersRoleDetailDesc:
      "募集詳細は順次更新します。詳細をご希望の方はお気軽にお問い合わせください。",
    careersBackHome: "ホームへ戻る →",
    pressKicker: "Press",
    pressTitle: "Kizuna の最新情報",
    pressDesc: "プレスリリース・メディア掲載・資料はこちら。",
    pressLink: "ニュースルームを見る →",
    newsroomKicker: "Newsroom",
    newsroomTitle: "Kizuna ニュースセンター",
    newsDetailBack: "ニュースセンターへ戻る →",
    newsItem1Title: "Kizuna が新しいプロダクトアップデートを公開",
    newsItem1Body: "同城マッチング、本人認証、コンテンツ体験をさらに強化しました。",
    newsItem2Title: "日本各地のコミュニティイベントを開始",
    newsItem2Body: "東京・大阪・名古屋で自然で安心な交流体験を提供します。",
    newsItem3Title: "本人動画認証を全面導入",
    newsItem3Body: "動画と本人確認でなりすましや迷惑行為を抑止します。",
    newsItem4Title: "コンテンツ拡張：短編動画＆ライブ",
    newsItem4Body: "より多くのコンテンツで興味から自然に会話が始まります。",
    newsItem5Title: "Kizuna 日本チームが拡大中",
    newsItem5Body: "プロダクト・運営・コンテンツの仲間を募集しています。",
    contactKicker: "Download",
    contactTitle: "今すぐ Kizuna をダウンロード",
    contactDesc: "QR でダウンロード、または提携相談をどうぞ。",
    downloadAppStore: "App Store",
    downloadGooglePlay: "Google Play",
    formNameLabel: "お名前",
    formNamePlaceholder: "お名前を入力してください",
    formRoleLabel: "所属 / 役割",
    formRolePlaceholder: "所属または役割を入力",
    formContactLabel: "連絡先",
    formContactPlaceholder: "電話番号またはメール",
    formMessageLabel: "メッセージ",
    formMessagePlaceholder: "内容を入力してください",
    formSubmit: "送信",
    formNote: "送信後、担当者よりご連絡いたします。",
    formThanks: "送信ありがとうございます。1営業日以内にご連絡します。",
    footerDesc: "在日華人向けの社交・恋活アプリ。",
    footerIcp: "〒170-0011 东京都丰岛区上池袋本町4--11-3三浦大厦",
    backTop: "トップに戻る",
  },
  zh: {
    langTag: "zh-CN",
    pageTitle: "Kizuna - 官网",
    brand: "Kizuna",
    navMission: "首页",
    navApproach: "产品方法",
    navLabs: "Kizuna Labs",
    navStories: "用户评论",
    navCareers: "加入我们",
    navPress: "媒体报道",
    navContact: "下载",
    menuToggle: "打开菜单",
    ctaPrimary: "下载",
    heroEyebrow: "在日华人专属社交约会平台",
    heroTitle: "去见你的最后一个“第一约会”。",
    heroSlogan:
      "与常见的恋爱交友软件相比，这完全是另一个层次。这一定是最棒的。",
    heroSubtitle:
      "Kizuna 为在日华人提供同城匹配、短视频、影视与直播体验，安全且真实。",
    heroPrimary: "下载应用",
    heroSecondary: "了解方法",
    heroDeviceTitle: "Kizuna Social",
    heroDeviceChip1: "同城",
    heroDeviceChip2: "短视频",
    heroDeviceChip3: "影视",
    heroDeviceChip4: "直播",
    missionKicker: "Our Approach",
    missionTitle: "从这里开始你的第一次约会",
    missionCopy1:
      "Kizuna 相信，每一个认真寻找关系的人，都值得遇见对的人。",
    missionCopy2:
      "我们不是为了让你停留在 App 里，而是为了帮助你走向真正重要的相遇。",
    missionCopy3:
      "在这个选择过载的时代，我们选择做得更少，却更准确。不是更多匹配，而是更好的相遇。",
    missionDesc:
      "Kizuna 不是让你无限滑动，而是帮助你遇见真正想见的人。",
    missionBody:
      "实名验证、同城匹配与内容互动，让每一次交流更有温度。",
    missionBtn: "了解更多",
    missionLink: "了解方法 →",
    missionPageKicker: "At the heart of Kizuna",
    missionPageTitle: "我们想创造一个更不孤单的世界",
    missionPageLead: "通过真实而亲密的线下连接。",
    missionPageValuesTitle: "Kizuna，用内容拉近距离，用相遇结束孤单。",
    missionPageValuesDesc:
      "不止有对的相遇，还有无限的内容。",
    missionPageValuesBody:
      "",
    missionPageValue1Title: "同城约会",
    missionPageValue1Desc:
      "就在你生活的城市，遇见想见的人。",
    missionPageValue2Title: "精彩短视频",
    missionPageValue2Desc:
      "分享你的生活，展示精彩的你。",
    missionPageValue3Title: "海量影视",
    missionPageValue3Desc:
      "3万+视频免费看，海量影视任你刷。",
    missionPageValue4Title: "美女直播",
    missionPageValue4Desc:
      "高颜值主播，都在这儿等你来聊。",
    missionPageApproachTitle: "其实我们更懂你",
    missionPageApproachDesc:
      "可信身份、同城匹配与内容互动，帮助你找到真正想见的人。",
    missionPageApproach1Title: "详细资料",
    missionPageApproach1Desc: "展示真实生活，建立信任。",
    missionPageApproach2Title: "高质量对话",
    missionPageApproach2Desc: "兴趣与内容引导自然交流。",
    missionPageApproach3Title: "智能匹配",
    missionPageApproach3Desc: "行为数据提升匹配质量。",
    missionPageBack: "返回首页",
    missionPageInsightsTitle: "app特点",
    missionPageInsight1Title: "同城速配",
    missionPageInsight1Desc:
      "距离显示，让你一眼看到与心仪对象的距离。我们把“距离”从社交阻碍变成优势，优先推荐更容易见面的人，减少无效匹配，让每一次连接都更有可能走向现实。",
    missionPageInsight2Title: "真人认证",
    missionPageInsight2Desc:
      "真人在线视频验证加上我们严格的身份与真人核验机制，减少虚假账号与骚扰行为，让你在更安心、更可信的环境中，放心开始每一次交流。",
    missionPageInsight3Title: "精彩短视频",
    missionPageInsight3Desc:
      "紧跟时事，第一时间呈现最新内容。通过不断更新的优质短视频，让你随时发现有趣的人和话题。",
    missionPageInsight4Title: "海量影视",
    missionPageInsight4Desc:
      "覆盖电影、短剧、用户自拍等多种内容类型，支持高清流畅播放，持续更新，让你随时都有好看的内容可看。",
    missionPageInsight5Title: "社区分享",
    missionPageInsight5Desc:
      "会员可以发布文字、图片或视频动态，展示自己的日常与心情，浏览社区内容，发现更多有趣的生活瞬间。",
    missionPageInsight6Title: "互动直播",
    missionPageInsight6Desc:
      "提供多样化的直播内容，支持实时互动与弹幕交流，画面高清流畅，让你随时进入正在进行的精彩直播。",
    missionPageInsight7Title: "回复提醒",
    missionPageInsight7Desc: "及时提醒，减少错过与失联。",
    missionPageInsight8Title: "智能匹配",
    missionPageInsight8Desc: "用反馈不断优化推荐。",
    approachKicker: "Product",
    approachTitle: "让每一次相遇，都更真实",
    approachDesc:
      "从同城相遇到实时互动，我们为真实和效率，重新设计社交。",
    approachCard1Title: "真人视频认证",
    approachCard1Desc: "必须真人出镜，通过视频完成认证。",
    approachCard2Title: "精准位置校验",
    approachCard2Desc: "基于真实定位，拒绝虚假异地。",
    approachCard3Title: "官方身份审核",
    approachCard3Desc: "多重资料审核，降低虚假账号。",
    approachCard4Title: "真实行为机制",
    approachCard4Desc: "聊天、互动、匹配，全程反作弊风控。",
    labsKicker: "",
    labsTitle: "在kizuna上约会",
    labsDesc:
      "告别尴尬的线下约会，加入到我们的单身社区，在这里寻找你喜欢的人。",
    labsLink: "看看用户评价 →",
    storiesKicker: "Stories",
    storiesTitle: "用户评论",
    story1Quote: "“Kizuna 让我很快遇到了同频的人。”",
    story1Author: "— Haruka · 东京",
    story2Quote: "“短视频让交流更自然。”",
    story2Author: "— Leo · 大阪",
    story3Quote: "“实名认证让我很安心。”",
    story3Author: "— Lan · 名古屋",
    careersKicker: "Work at Kizuna",
    careersTitle: "一起做有意义的社交产品",
    careersDesc:
      "我们希望让约会更有趣，让你的生活更精彩。",
    careersBtn: "加入我们",
    careersPageKicker: "招聘",
    careersPageTitle: "帮助更多人找到对的人",
    careersPageLead:
      "我们正在打造更人性、更有效的社交产品，期待与你一起实现。",
    careersPageCta: "查看职位",
    careersValueKicker: "多元与包容",
    careersValueTitle: "多元激发创新。",
    careersValueLead:
      "我们相信多元背景与思维带来更好的成果。",
    careersValue1Title: "打开圈层",
    careersValue1Desc: "积极欢迎并包容不同背景的人。",
    careersValue2Title: "以爱为先",
    careersValue2Desc: "坦诚交流，彼此尊重与成长。",
    careersValue3Title: "承认未知",
    careersValue3Desc: "保持好奇与学习，持续精进。",
    careersStatsKicker: "市场潜力",
    careersStatsTitle: "市场潜力",
    careersStat1Value: "42%",
    careersStat1Label: "核心年龄段单身人群占比",
    careersStat2Value: "78%",
    careersStat2Label: "线上社交使用意愿",
    careersStat3Value: "65%",
    careersStat3Label: "移动端社交使用频次",
    careersPerkKicker: "福利待遇",
    careersPerkTitle: "更好工作，更好生活。",
    careersPerk1: "混合办公与远程支持",
    careersPerk2: "高质量健康保障",
    careersPerk3: "充足假期与健康日",
    careersPerk4: "学习成长补贴",
    careersPerk5: "育儿与家庭支持",
    careersPerk6: "社区公益支持",
    careersOpenKicker: "职位空缺",
    careersOpenTitle: "我们正在招聘",
    careersOpenLead: "欢迎关注最新岗位信息。",
    careersGroup1Title: "工程",
    careersGroup1Count: "（11）",
    careersGroup1Desc: "每天都在创造各种小解决方案，以改善用户体验。",
    careersGroup2Title: "营销",
    careersGroup2Count: "（04）",
    careersGroup2Desc: "连接品牌与用户，让更多人认识 Kizuna。",
    careersGroup3Title: "产品",
    careersGroup3Count: "（07）",
    careersGroup3Desc: "通过创新功能和优化体验解决用户问题。",
    careersRole1: "Android 工程师  东京",
    careersRole2: "iOS 工程师  东京",
    careersRole3: "机器学习工程师（约会结果）  东京",
    careersRole4: "高级数据工程师  东京",
    careersRole5: "平台高级工程经理  东京",
    careersRole6: "高级 iOS 工程师  东京",
    careersRole7: "品牌战略总监  东京",
    careersRole8: "对外沟通总监  东京",
    careersRole9: "编辑总监  东京",
    careersRole10: "产品营销经理  东京",
    careersRole11: "首席产品设计师（约会结果）  东京",
    careersRole12: "约会结果首席产品经理  东京",
    careersRole13: "首席产品经理（账户完整性）  东京",
    careersRole14: "信任与安全首席产品设计师  东京",
    careersRoleDetailDesc:
      "职位详情将持续更新，欢迎与我们联系了解更多。",
    careersBackHome: "返回首页 →",
    pressKicker: "Press",
    pressTitle: "Kizuna 媒体报道",
    pressDesc: "新闻稿、媒体报道与资料包。",
    pressLink: "进入新闻室 →",
    newsroomKicker: "新闻中心",
    newsroomTitle: "Kizuna 新闻中心",
    newsDetailBack: "返回新闻中心 →",
    newsItem1Title: "Kizuna 完成新一轮产品升级",
    newsItem1Body: "聚焦同城速配、真人认证与内容推荐，提升真实连接效率。",
    newsItem2Title: "日本本地社群活动正式开启",
    newsItem2Body: "覆盖东京、大阪、名古屋等城市，打造更自然的线下社交体验。",
    newsItem3Title: "真人视频认证机制全面上线",
    newsItem3Body: "视频+真人核验双重流程，减少虚假账号与骚扰行为。",
    newsItem4Title: "内容生态扩展：短视频与直播专区",
    newsItem4Body: "更多互动场景，让用户在交流前建立真实兴趣连接。",
    newsItem5Title: "Kizuna 日本团队持续扩张",
    newsItem5Body: "诚邀产品、运营与内容伙伴加入。",
    contactKicker: "Download",
    contactTitle: "立即下载 Kizuna",
    contactDesc: "扫码下载或留下合作需求。",
    downloadAppStore: "App Store",
    downloadGooglePlay: "Google Play",
    formNameLabel: "姓名",
    formNamePlaceholder: "请输入您的姓名",
    formRoleLabel: "角色 / 机构",
    formRolePlaceholder: "请输入机构或角色",
    formContactLabel: "联系方式",
    formContactPlaceholder: "手机号或邮箱",
    formMessageLabel: "留言",
    formMessagePlaceholder: "请描述您的需求",
    formSubmit: "提交",
    formNote: "提交后我们将安排专员与您对接。",
    formThanks: "感谢提交，我们将在1个工作日内联系您。",
    footerDesc: "在日华人专属社交约会平台。",
    footerIcp: "〒170-0011 东京都丰岛区上池袋本町4--11-3三浦大厦",
    backTop: "回到顶部",
  },
  en: {
    langTag: "en",
    pageTitle: "Kizuna - Official Site",
    brand: "Kizuna",
    navMission: "Product",
    navApproach: "Approach",
    navLabs: "Labs",
    navStories: "Stories",
    navCareers: "Careers",
    navPress: "Press",
    navContact: "Download",
    menuToggle: "Open menu",
    ctaPrimary: "Download",
    heroEyebrow: "Social & dating app for Chinese in Japan",
    heroTitle: "Go on your last first date.",
    heroSlogan:
      "Beyond typical dating apps. This is on another level — the best experience.",
    heroSubtitle:
      "Kizuna brings local matching, short video, movies, and live experiences that feel safe and real.",
    heroPrimary: "Download the app",
    heroSecondary: "How we do it",
    heroDeviceTitle: "Kizuna Social",
    heroDeviceChip1: "Local",
    heroDeviceChip2: "Short",
    heroDeviceChip3: "Movies",
    heroDeviceChip4: "Live",
    missionKicker: "Our Approach",
    missionTitle: "Start your first date here",
    missionCopy1:
      "Kizuna believes that anyone sincerely looking for a relationship deserves the right person.",
    missionCopy2:
      "We’re not here to keep you in the app, but to guide you to the connections that matter.",
    missionCopy3:
      "In an age of too many choices, we choose less but more precise — not more matches, but better ones.",
    missionDesc:
      "Kizuna helps you meet people you actually want to go out with, not keep swiping.",
    missionBody:
      "Verification, local matching, and content-driven interaction make every connection feel real.",
    missionBtn: "Learn more",
    missionLink: "How we do it →",
    missionPageKicker: "At the heart of Kizuna",
    missionPageTitle: "We want to create a less lonely world",
    missionPageLead: "By inspiring intimate, in-person connections.",
    missionPageValuesTitle: "Kizuna — bringing people closer through content, ending loneliness with real encounters.",
    missionPageValuesDesc:
      "Not just the right matches, but endless content too.",
    missionPageValuesBody:
      "",
    missionPageValue1Title: "Local Dating",
    missionPageValue1Desc:
      "Meet the people you want to see, right in your city.",
    missionPageValue2Title: "Short Videos",
    missionPageValue2Desc:
      "Share your life and show your best self.",
    missionPageValue3Title: "Movies",
    missionPageValue3Desc:
      "30,000+ videos to watch, endless movies to stream.",
    missionPageValue4Title: "Live",
    missionPageValue4Desc:
      "High‑profile hosts are here waiting to chat with you.",
    missionPageApproachTitle: "We actually understand you better.",
    missionPageApproachDesc:
      "Trusted identity, local matching, and content interactions.",
    missionPageApproach1Title: "Detailed profiles",
    missionPageApproach1Desc: "Share real life and build trust.",
    missionPageApproach2Title: "Great conversations",
    missionPageApproach2Desc: "Prompts and interests spark natural chat.",
    missionPageApproach3Title: "Smart matching",
    missionPageApproach3Desc: "Behavior and preferences improve quality.",
    missionPageBack: "Back to home",
    missionPageInsightsTitle: "App features",
    missionPageInsight1Title: "Detailed profiles",
    missionPageInsight1Desc: "Show real life and build trust.",
    missionPageInsight2Title: "Proven prompts",
    missionPageInsight2Desc: "Spark more natural conversations.",
    missionPageInsight3Title: "Conversation starters",
    missionPageInsight3Desc: "Like specifics to start a chat.",
    missionPageInsight4Title: "Matchmaking algorithm",
    missionPageInsight4Desc: "Understand preferences, improve quality.",
    missionPageInsight5Title: "Meaningful likes",
    missionPageInsight5Desc: "Fewer, but more intentional.",
    missionPageInsight6Title: "Transparent likes",
    missionPageInsight6Desc: "See who likes you.",
    missionPageInsight7Title: "Reply reminders",
    missionPageInsight7Desc: "Don’t miss your turn to reply.",
    missionPageInsight8Title: "Smart matches",
    missionPageInsight8Desc: "Optimize with feedback.",
    approachKicker: "Product",
    approachTitle: "Make every connection more real",
    approachDesc:
      "From local encounters to real-time interaction, we redesign social experiences for authenticity and efficiency.",
    approachCard1Title: "Live Video Verification",
    approachCard1Desc: "Appear on camera to complete verification.",
    approachCard2Title: "Precise Location Checks",
    approachCard2Desc: "Based on real location, no fake distance.",
    approachCard3Title: "Official Identity Review",
    approachCard3Desc: "Multi‑step reviews reduce fake accounts.",
    approachCard4Title: "Real Behavior Safeguards",
    approachCard4Desc: "Chat, interact, match with anti‑fraud protection.",
    labsKicker: "",
    labsTitle: "Date on Kizuna",
    labsDesc:
      "Say goodbye to awkward offline dates. Join our singles community and find the people you like.",
    labsLink: "What our users say →",
    storiesKicker: "Stories",
    storiesTitle: "What our users say",
    story1Quote:
      "“Kizuna helped me meet someone who really matched my vibe.”",
    story1Author: "— Haruka · Tokyo",
    story2Quote:
      "“Short videos made it easy to start real conversations.”",
    story2Author: "— Leo · Osaka",
    story3Quote:
      "“I felt safe with verification and privacy settings.”",
    story3Author: "— Lan · Nagoya",
    careersKicker: "Work at Kizuna",
    careersTitle: "Let’s work together",
    careersDesc:
      "We want dating to be more fun and make your life more vibrant.",
    careersBtn: "Join us",
    careersPageKicker: "Careers",
    careersPageTitle: "Help more people find their person.",
    careersPageLead:
      "We’re building a more human, more effective dating experience. Come build it with us.",
    careersPageCta: "Find openings",
    careersValueKicker: "Diversity & Inclusion",
    careersValueTitle: "Diversity inspires innovation.",
    careersValueLead:
      "We believe success is created by a workforce with diverse ideas and backgrounds.",
    careersValue1Title: "Open the circle",
    careersValue1Desc: "Actively welcome and include everyone.",
    careersValue2Title: "Lead with love",
    careersValue2Desc: "Practice candor, empathy, and shared learning.",
    careersValue3Title: "Know our unknowns",
    careersValue3Desc: "Stay curious and keep growing.",
    careersStatsKicker: "Market potential",
    careersStatsTitle: "Market potential",
    careersStat1Value: "42%",
    careersStat1Label: "share of singles in core age group",
    careersStat2Value: "78%",
    careersStat2Label: "willingness to use online social apps",
    careersStat3Value: "65%",
    careersStat3Label: "mobile social usage frequency",
    careersPerkKicker: "Perks & Benefits",
    careersPerkTitle: "Do your best work, live your best life.",
    careersPerk1: "Hybrid and remote-friendly work",
    careersPerk2: "Comprehensive health coverage",
    careersPerk3: "Generous time off and wellness days",
    careersPerk4: "Learning & development stipend",
    careersPerk5: "Parental leave and planning support",
    careersPerk6: "Community and volunteering days",
    careersOpenKicker: "Openings",
    careersOpenTitle: "We’re hiring.",
    careersOpenLead: "Our teams are growing. We’d love to meet you.",
    careersGroup1Title: "Engineering",
    careersGroup1Count: "(11)",
    careersGroup1Desc:
      "Solve real problems and build a better experience every day.",
    careersGroup2Title: "Marketing",
    careersGroup2Count: "(04)",
    careersGroup2Desc:
      "Connect the brand and the community through thoughtful storytelling.",
    careersGroup3Title: "Product",
    careersGroup3Count: "(07)",
    careersGroup3Desc:
      "Build new features and refine the experience end-to-end.",
    careersRole1: "Android Engineer  Tokyo",
    careersRole2: "iOS Engineer  Tokyo",
    careersRole3: "ML Engineer (Outcomes)  Tokyo",
    careersRole4: "Senior Data Engineer  Tokyo",
    careersRole5: "Platform Engineering Manager  Tokyo",
    careersRole6: "Senior iOS Engineer  Tokyo",
    careersRole7: "Brand Strategy Director  Tokyo",
    careersRole8: "Comms Director  Tokyo",
    careersRole9: "Editorial Director  Tokyo",
    careersRole10: "Product Marketing Manager  Tokyo",
    careersRole11: "Lead Product Designer (Outcomes)  Tokyo",
    careersRole12: "Lead PM, Outcomes  Tokyo",
    careersRole13: "Lead PM, Account Integrity  Tokyo",
    careersRole14: "Lead Product Designer, Trust & Safety  Tokyo",
    careersRoleDetailDesc:
      "Role details will be updated soon. Contact us to learn more.",
    careersBackHome: "Back to home →",
    pressKicker: "Press",
    pressTitle: "Kizuna in the headlines",
    pressDesc: "Press releases, media coverage, and press kits.",
    pressLink: "Visit our newsroom →",
    newsroomKicker: "Newsroom",
    newsroomTitle: "Kizuna Newsroom",
    newsDetailBack: "Back to newsroom →",
    newsItem1Title: "Kizuna ships a major product update",
    newsItem1Body: "Enhancing local matching, identity checks, and content discovery.",
    newsItem2Title: "Community events launch across Japan",
    newsItem2Body: "Bringing safer, more natural offline connections to major cities.",
    newsItem3Title: "Video verification rolls out",
    newsItem3Body: "Dual verification reduces fake accounts and harassment.",
    newsItem4Title: "Content expands: short video + live",
    newsItem4Body: "More ways to connect through shared interests and real-time moments.",
    newsItem5Title: "Kizuna Japan team is growing",
    newsItem5Body: "We’re hiring across product, ops, and content.",
    contactKicker: "Download",
    contactTitle: "Download Kizuna now",
    contactDesc: "Scan to download or leave a partnership request.",
    downloadAppStore: "App Store",
    downloadGooglePlay: "Google Play",
    formNameLabel: "Name",
    formNamePlaceholder: "Enter your name",
    formRoleLabel: "Role / Organization",
    formRolePlaceholder: "Enter your role or organization",
    formContactLabel: "Contact",
    formContactPlaceholder: "Phone or email",
    formMessageLabel: "Message",
    formMessagePlaceholder: "Tell us your needs",
    formSubmit: "Submit",
    formNote: "We will contact you within 1 business day.",
    formThanks: "Thanks! We'll reach out within 1 business day.",
    footerDesc: "Social & dating app for Chinese in Japan.",
    footerIcp: "〒170-0011 东京都丰岛区上池袋本町4--11-3三浦大厦",
    backTop: "Back to top",
  },
};

const closeNav = () => {
  if (mainNav && mainNav.classList.contains("open")) {
    mainNav.classList.remove("open");
  }
};

const applyTranslations = (lang) => {
  const copy = translations[lang] || translations.ja;
  document.documentElement.lang = copy.langTag;
  document.title = copy.pageTitle;

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    if (copy[key]) {
      el.textContent = copy[key];
    }
  });

  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.dataset.i18nPlaceholder;
    if (copy[key]) {
      el.setAttribute("placeholder", copy[key]);
    }
  });

  document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
    const key = el.dataset.i18nAria;
    if (copy[key]) {
      el.setAttribute("aria-label", copy[key]);
    }
  });

  if (formNote) {
    formNote.textContent = copy.formNote;
  }
};

let cmsContent = null;
let newsSliderTimer = null;

const formatCount = (lang, count) => {
  const padded = String(count).padStart(2, "0");
  if (lang === "en") {
    return `(${padded})`;
  }
  return `（${padded}）`;
};

const getCmsText = (block, lang) => {
  if (!block) return "";
  return block[lang] || block.zh || block.ja || block.en || "";
};

const fetchRoleDesc = async (roleId, lang) => {
  if (!roleId) return "";
  try {
    const response = await fetch("/api/content", { cache: "no-store" });
    if (!response.ok) return "";
    const data = await response.json();
    const previous = cmsContent;
    cmsContent = data;
    const role = findRoleById(roleId);
    return getCmsText(role?.desc, lang) || "";
  } catch (error) {
    return "";
  }
};

const findRoleById = (roleId) => {
  if (!cmsContent || !Array.isArray(cmsContent.jobs) || !roleId) return null;
  for (const group of cmsContent.jobs) {
    const roles = Array.isArray(group.roles) ? group.roles : [];
    const match = roles.find((role) => role.id === roleId);
    if (match) return match;
  }
  return null;
};

const getReadMoreLabel = (lang) => {
  if (lang === "en") return "Read more";
  if (lang === "ja") return "続きを読む";
  return "查看全文";
};

const applyCmsContent = (lang) => {
  if (!cmsContent) return;

  const newsSlider = document.querySelector("[data-news-slider]");
  if (newsSlider && Array.isArray(cmsContent.news)) {
    const items = cmsContent.news.slice(0, 5);
    newsSlider.innerHTML = "";
    items.forEach((item, index) => {
      const article = document.createElement("article");
      article.className = `news-item${index === 0 ? " is-active" : ""}`;
      const title = document.createElement("h3");
      title.className = "news-item-title";
      title.textContent = getCmsText(item.title, lang);
      const body = document.createElement("p");
      body.className = "news-item-body";
      body.textContent = getCmsText(item.body, lang);
      const more = document.createElement("span");
      more.className = "news-item-more";
      const link = document.createElement("a");
      link.className = "news-item-link";
      link.href = `./news-detail.html?id=${index}`;
      link.textContent = `...${getReadMoreLabel(lang)}`;
      more.appendChild(link);
      body.appendChild(more);
      article.appendChild(title);
      article.appendChild(body);
      newsSlider.appendChild(article);
    });
    initNewsSlider();
  }

  const jobGroups = document.querySelector("[data-job-groups]");
  if (jobGroups && Array.isArray(cmsContent.jobs)) {
    jobGroups.innerHTML = "";
    cmsContent.jobs.forEach((group) => {
      const groupEl = document.createElement("div");
      groupEl.className = "opening-group";
      const info = document.createElement("div");
      info.className = "opening-info";
      const title = document.createElement("h3");
      const titleSpan = document.createElement("span");
      titleSpan.textContent = getCmsText(group.title, lang);
      const countSpan = document.createElement("span");
      countSpan.className = "opening-count";
      const roleCount = Array.isArray(group.roles) ? group.roles.length : 0;
      countSpan.textContent = formatCount(lang, roleCount);
      title.appendChild(titleSpan);
      title.appendChild(document.createTextNode(" "));
      title.appendChild(countSpan);
      const desc = document.createElement("p");
      desc.textContent = getCmsText(group.desc, lang);
      info.appendChild(title);
      info.appendChild(desc);

      const list = document.createElement("div");
      list.className = "opening-list";
      (group.roles || []).forEach((role) => {
        const link = document.createElement("a");
        link.className = "opening-item";
        link.href = "#";
        const roleTitle = getCmsText(role.title, lang);
        const roleLocation = getCmsText(role.location, lang);
        link.dataset.roleTitle = roleTitle;
        link.dataset.roleLocation = roleLocation;
        if (role.id) {
          link.dataset.roleId = role.id;
        }
        link.innerHTML = `${roleTitle} <span>${roleLocation}</span>`;
        list.appendChild(link);
      });

      groupEl.appendChild(info);
      groupEl.appendChild(list);
      jobGroups.appendChild(groupEl);
    });
  }

  const newsDetail = document.querySelector("[data-news-detail]");
  if (newsDetail && Array.isArray(cmsContent.news)) {
    const params = new URLSearchParams(window.location.search);
    const requestedIndex = Number(params.get("id"));
    const selected =
      cmsContent.news[requestedIndex] || cmsContent.news[0] || null;
    if (selected) {
      const titleEl = newsDetail.querySelector("[data-news-detail-title]");
      const bodyEl = newsDetail.querySelector("[data-news-detail-body]");
      if (titleEl) titleEl.textContent = getCmsText(selected.title, lang);
      if (bodyEl) bodyEl.textContent = getCmsText(selected.body, lang);
    }
  }
};

const loadCmsContent = async () => {
  const fetchJson = async (url) => {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`Failed to load ${url}`);
    return response.json();
  };
  try {
    cmsContent = await fetchJson("/api/content");
  } catch (error) {
    try {
      cmsContent = await fetchJson("./content.json");
    } catch (fallbackError) {
      cmsContent = null;
    }
  }
  const currentLang = localStorage.getItem("kizuna-lang") || "ja";
  applyCmsContent(currentLang);
};

const initNewsSlider = () => {
  const newsSlider = document.querySelector("[data-news-slider]");
  if (!newsSlider) return;
  if (newsSliderTimer) {
    window.clearInterval(newsSliderTimer);
    newsSliderTimer = null;
  }
  const allNewsItems = Array.from(newsSlider.querySelectorAll(".news-item"));
  const newsItems = allNewsItems.slice(0, 5);
  allNewsItems.slice(5).forEach((item) => item.remove());
  const progressWrap = document.querySelector("[data-news-progress]");
  let progressBars = [];
  if (progressWrap) {
    progressWrap.innerHTML = "";
    progressBars = newsItems.map((_, index) => {
      const bar = document.createElement("span");
      bar.className = "progress-bar";
      bar.dataset.index = String(index);
      bar.setAttribute("role", "button");
      bar.setAttribute("tabindex", "0");
      bar.setAttribute("aria-label", `Show news item ${index + 1}`);
      progressWrap.appendChild(bar);
      return bar;
    });
  }
  if (newsItems.length > 1) {
    let currentIndex = 0;
    const duration = 4500;
    const showItem = (index) => {
      newsItems.forEach((item, i) =>
        item.classList.toggle("is-active", i === index),
      );
      progressBars.forEach((bar, i) => {
        bar.classList.remove("is-active");
        void bar.offsetWidth;
        if (i === index) {
          bar.style.setProperty("--progress-duration", `${duration}ms`);
          bar.classList.add("is-active");
        }
      });
    };
    const startTimer = () => {
      if (newsSliderTimer) {
        window.clearInterval(newsSliderTimer);
      }
      newsSliderTimer = window.setInterval(() => {
        currentIndex = (currentIndex + 1) % newsItems.length;
        showItem(currentIndex);
      }, duration);
    };
    const jumpTo = (index) => {
      currentIndex = Math.max(0, Math.min(index, newsItems.length - 1));
      showItem(currentIndex);
      startTimer();
    };
    showItem(currentIndex);
    startTimer();
    if (progressWrap) {
      if (progressWrap._newsClickHandler) {
        progressWrap.removeEventListener(
          "click",
          progressWrap._newsClickHandler,
        );
      }
      if (progressWrap._newsKeyHandler) {
        progressWrap.removeEventListener(
          "keydown",
          progressWrap._newsKeyHandler,
        );
      }
      progressWrap._newsClickHandler = (event) => {
        const bar = event.target.closest(".progress-bar");
        if (!bar || !progressWrap.contains(bar)) return;
        const targetIndex = Number(bar.dataset.index);
        if (Number.isNaN(targetIndex)) return;
        jumpTo(targetIndex);
      };
      progressWrap._newsKeyHandler = (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const bar = event.target.closest(".progress-bar");
        if (!bar || !progressWrap.contains(bar)) return;
        event.preventDefault();
        const targetIndex = Number(bar.dataset.index);
        if (Number.isNaN(targetIndex)) return;
        jumpTo(targetIndex);
      };
      progressWrap.addEventListener("click", progressWrap._newsClickHandler);
      progressWrap.addEventListener("keydown", progressWrap._newsKeyHandler);
    }
  } else if (newsItems.length === 1 && progressBars[0]) {
    progressBars[0].classList.add("is-active");
  }
};

const setLanguage = (lang) => {
  applyTranslations(lang);
  applyCmsContent(lang);
  localStorage.setItem("kizuna-lang", lang);
  langButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.lang === lang);
  });
};

if (menuToggle && mainNav) {
  menuToggle.addEventListener("click", () => {
    mainNav.classList.toggle("open");
  });
}

document.querySelectorAll(".nav a").forEach((link) => {
  link.addEventListener("click", () => {
    closeNav();
  });
});

langButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setLanguage(button.dataset.lang);
  });
});

const preferredLang = localStorage.getItem("kizuna-lang") || "ja";
setLanguage(preferredLang);
loadCmsContent();

if (backTop) {
  window.addEventListener("scroll", () => {
    if (window.scrollY > 400) {
      backTop.classList.add("show");
    } else {
      backTop.classList.remove("show");
    }
  });

  backTop.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

if (contactForm) {
  contactForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const lang = localStorage.getItem("kizuna-lang") || "ja";
    const copy = translations[lang] || translations.ja;
    formNote.textContent = copy.formThanks;
    contactForm.reset();
  });
}

const valuesSection = document.querySelector(".values-section");
const valueNumberTexts = document.querySelectorAll(".value-number-svg text");

valueNumberTexts.forEach((textEl) => {
  try {
    const length = textEl.getComputedTextLength();
    textEl.style.setProperty("--stroke-length", `${Math.ceil(length)}`);
  } catch (error) {
    // Ignore if the SVG text length cannot be measured.
  }
});

if (valuesSection) {
  const revealValues = () => valuesSection.classList.add("is-visible");

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          revealValues();
          observer.disconnect();
        }
      },
      { threshold: 0.2 },
    );
    observer.observe(valuesSection);
  }
}

const insightsSection = document.querySelector(".insights-section");
if (insightsSection && "IntersectionObserver" in window) {
  const insightCards = insightsSection.querySelectorAll(".insights-card");
  const observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        insightCards.forEach((card, index) => {
          window.setTimeout(() => {
            card.classList.add("is-visible");
          }, index * 220);
        });
        observer.disconnect();
      }
    },
    { threshold: 0.2 },
  );
  observer.observe(insightsSection);
}

const roleModal = document.querySelector("[data-role-modal]");
if (roleModal) {
  const roleTitle = roleModal.querySelector("#roleModalTitle");
  const roleLocation = roleModal.querySelector("#roleModalLocation");
  const roleDesc = roleModal.querySelector(".role-modal-desc");
  const closeButtons = roleModal.querySelectorAll("[data-role-close]");

  const closeRoleModal = () => {
    roleModal.classList.remove("is-open");
    roleModal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  };

  const openRoleModal = (item) => {
    const location =
      item.dataset.roleLocation ||
      item.querySelector("span")?.textContent.trim() ||
      "";
    const title =
      item.dataset.roleTitle ||
      item.textContent.replace(location, "").trim();
    const lang = localStorage.getItem("kizuna-lang") || "ja";
    const fallbackDesc =
      (translations[lang] || translations.ja).careersRoleDetailDesc || "";
    const roleId = item.dataset.roleId;
    const roleData = findRoleById(roleId);
    const cmsDesc = getCmsText(roleData?.desc, lang);
    const desc = cmsDesc || fallbackDesc;
    roleTitle.textContent = title;
    roleLocation.textContent = location;
    if (roleDesc) roleDesc.textContent = desc;
    roleModal.classList.add("is-open");
    roleModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    if (!cmsDesc && roleId && roleDesc) {
      fetchRoleDesc(roleId, lang).then((freshDesc) => {
        if (freshDesc) {
          roleDesc.textContent = freshDesc;
        }
      });
    }
  };

  document.addEventListener("click", (event) => {
    const item = event.target.closest(".opening-item");
    if (!item) return;
    event.preventDefault();
    openRoleModal(item);
  });

  closeButtons.forEach((btn) => {
    btn.addEventListener("click", closeRoleModal);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && roleModal.classList.contains("is-open")) {
      closeRoleModal();
    }
  });
}

initNewsSlider();

const careersStats = document.querySelector(".careers-stats");
if (careersStats) {
  const metricValues = careersStats.querySelectorAll(".metric-value");
  const animateNumber = (el) => {
    if (el.dataset.animated === "true") return;
    el.dataset.animated = "true";
    const target = Number(el.dataset.target || el.textContent) || 0;
    const duration = 1200;
    const start = performance.now();
    const step = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const value = Math.floor(target * progress);
      el.textContent = String(value);
      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = String(target);
      }
    };
    requestAnimationFrame(step);
  };

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          metricValues.forEach((el, index) => {
            window.setTimeout(() => animateNumber(el), index * 180);
          });
          observer.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    observer.observe(careersStats);
  } else {
    metricValues.forEach((el) => animateNumber(el));
  }
}
