// The interface in English and Simplified Chinese, like the app. Content shows in Simplified Chinese where a checked
// translation exists, and in English otherwise.
export type Language = 'en' | 'zh-Hans';

const zh: Record<string, string> = {
	'Psst': 'Psst',
	'Surprising, sourced stories about places you can stand in front of.': '关于你能亲眼看到的地方的意外故事，每个都有出处。',
	'Cities': '城市',
	'places': '个地方',
	'Places': '地方',
	'Trails': '路线',
	'Stories': '故事',
	'Look': '去看看',
	'Sources': '出处',
	'Claims and their sources': '每项说法的出处',
	'Legend': '传说',
	'Disputed': '有争议',
	'The popular version': '流传的说法',
	'Guide': '简介',
	'Key facts': '基本信息',
	'Photos': '照片',
	'Photo by': '摄影',
	'Then': '过去',
	'Now': '现在',
	'Last checked': '最近核实',
	'Report a problem': '报告问题',
	'What is wrong?': '哪里有问题？',
	'Wrong': '内容有误',
	'Outdated': '已过时',
	'Wrong location': '位置不对',
	'Offensive': '内容不当',
	'Other': '其他',
	'Details (optional)': '详细说明（选填）',
	'Send': '发送',
	'Thank you. It will be checked again.': '谢谢。我们会重新核实。',
	'That didn’t send. Try again later.': '没有发送成功，请稍后再试。',
	'Needs JavaScript to send.': '发送需要启用 JavaScript。',
	'Search': '搜索',
	'Search this city': '搜索这座城市',
	'No places match.': '没有符合的地方。',
	'Map': '地图',
	'Open in OpenStreetMap': '在 OpenStreetMap 中打开',
	'Neighborhood': '街区',
	'Tags': '标签',
	'Stops': '站点',
	'Back to': '返回',
	'Get the app': '下载 App',
	'In English': 'English',
	'中文': '中文',
	'Location from': '位置来自',
	'Skip to content': '跳到内容',
	'Places with this tag': '带有这个标签的地方',
	'About Psst': '关于 Psst',
	'name': '名字由来',
	'hidden': '隐藏的细节',
	'history': '历史',
	'design': '设计',
	'engineering': '工程',
	'people': '人物',
	'pop': '流行文化',
	'quirk': '奇闻',
	'transit': '交通',
	'crossing': '桥梁和隧道',
	'street': '街道',
	'building': '建筑',
	'worship': '宗教场所',
	'memorial': '纪念物',
	'green': '公园和绿地',
	'water': '水边',
	'culture': '文化'
};

const en: Record<string, string> = {
	name: 'Name origin', hidden: 'Hidden detail', history: 'History', design: 'Design', engineering: 'Engineering',
	people: 'People', pop: 'Pop culture', quirk: 'Quirk', transit: 'Transport', crossing: 'Bridge or tunnel',
	street: 'Street', building: 'Building', worship: 'Place of worship', memorial: 'Monument', green: 'Park or garden',
	water: 'Water', culture: 'Culture'
};

export function t(language: Language, text: string): string {
	return language === 'zh-Hans' ? (zh[text] ?? text) : (en[text] ?? text);
}

/** A content field in the reader's language when a checked translation has it. */
export function field<T extends object>(language: Language, item: T, key: keyof T & string): string {
	const translations = (item as { translations?: Record<string, Record<string, unknown> | undefined> }).translations;
	const translated = language === 'zh-Hans' ? translations?.['zh-Hans']?.[key] : undefined;
	const original = (item as Record<string, unknown>)[key];
	return String(typeof translated === 'string' && translated ? translated : (original ?? ''));
}

export function name(language: Language, place: { name: string; localName?: { lang: string; name: string } | null;
	names?: Record<string, string> }): string {
	if (language === 'zh-Hans') return place.names?.['zh-Hans'] ?? (place.localName?.lang === 'zh-Hans' ? place.localName.name : place.name);
	return place.name;
}
