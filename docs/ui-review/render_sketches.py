from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

OUT = Path(__file__).parent
S = 2
INK, WHITE, YELLOW, BLUE, GREEN, RED = '#26211F', '#FFFFFF', '#FFD84D', '#4D8FFF', '#68BA88', '#EB7465'
MUTED, RULE, PALE_Y, PALE_B, PALE_G, PALE_R = '#716C67', '#DDDAD5', '#FFF5C7', '#EAF2FF', '#EAF6EE', '#FFF0EC'
REG, BOLD = 'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc'
FONTS = {}
ASSETS = {}

def font(size, bold=False):
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype(BOLD if bold else REG, round(size*S))
    return FONTS[key]

class C:
    def __init__(self, w, h, bg=WHITE):
        self.w, self.h = w, h
        self.im = Image.new('RGB', (round(w*S), round(h*S)), bg)
        self.d = ImageDraw.Draw(self.im)
    def box(self, x, y, w, h, fill=WHITE, outline=INK, radius=12, stroke=2):
        bounds = tuple(round(v*S) for v in (x, y, x+w, y+h))
        self.d.rounded_rectangle(bounds, radius=round(radius*S), fill=fill, outline=outline, width=round(stroke*S))
    def line(self, pts, fill=INK, width=2):
        self.d.line([(round(x*S),round(y*S)) for x,y in pts], fill=fill, width=round(width*S), joint='curve')
    def ellipse(self,x,y,w,h,fill=WHITE,outline=INK,stroke=2):
        self.d.ellipse(tuple(round(v*S) for v in (x,y,x+w,y+h)),fill=fill,outline=outline,width=round(stroke*S))
    def poly(self, pts, fill=WHITE, outline=INK, stroke=2):
        points=[(round(x*S),round(y*S)) for x,y in pts]
        self.d.polygon(points,fill=fill)
        if outline: self.d.line(points+[points[0]],fill=outline,width=round(stroke*S),joint='curve')
    def txt(self,x,y,t,size=16,fill=INK,bold=False,center=False):
        f=font(size,bold)
        if center: x -= self.d.textlength(t,font=f)/(2*S)
        self.d.text((round(x*S),round(y*S)),t,font=f,fill=fill,anchor='lt')
    def para(self,x,y,t,width,size=16,fill=INK,bold=False,leading=1.6):
        lines=[]
        for block in t.split('\n'):
            line=''
            for ch in block:
                if self.d.textlength(line+ch,font=font(size,bold)) > width*S and line:
                    if ch in '，。！？；：、）】》,.!?;:' and len(line)>1:
                        lines.append(line[:-1]); line=line[-1]+ch
                    else:
                        lines.append(line); line=ch
                else: line+=ch
            lines.append(line)
        for line in lines:
            self.txt(x,y,line,size,fill,bold); y+=size*leading
        return y
    def mark(self,x,y,n=12,correct=True,color=INK):
        if correct: self.line([(x,y+n*.5),(x+n*.35,y+n),(x+n,y)],color,2)
        else:
            self.line([(x,y),(x+n,y+n)],color,2)
            self.line([(x,y+n),(x+n,y)],color,2)
    def button(self,x,y,w,t,fill=YELLOW,secondary=False,h=50):
        if not secondary: self.box(x+3,y+4,w,h,INK,INK,12,0)
        self.box(x,y,w,h,WHITE if secondary else fill,INK,12,2)
        self.txt(x+w/2,y+(h-18)/2,t,18,bold=True,center=True)
    def pill(self,x,y,t,fill=PALE_Y,w=None):
        w=w or self.d.textlength(t,font=font(12,True))/S+22
        self.box(x,y,w,26,fill,INK,8,1.3)
        self.txt(x+w/2,y+7,t,12,bold=True,center=True)
    def asset(self,name,x,y,w,h):
        if name not in ASSETS: ASSETS[name]=Image.open(OUT/'mascots'/name).convert('RGBA')
        art=ASSETS[name]
        ratio=min(w*S/art.width,h*S/art.height)
        tile=art.resize((round(art.width*ratio),round(art.height*ratio)),Image.Resampling.LANCZOS)
        pos=(round(x*S+(w*S-tile.width)/2),round(y*S+(h*S-tile.height)/2))
        self.im.paste(tile,pos,tile)
    def mascot(self,x,y,k=1,mood='happy',color=BLUE):
        self.asset('A-u-book-spirit.png',x,y,132*k,110*k)
    def pencil_line(self,x,y,w=120):
        self.line([(x,y),(x+w*.3,y-2),(x+w*.75,y+1),(x+w,y-1)],BLUE,2)
    def paste(self,other,x,y,w=None):
        image=other.im
        if w: image=image.resize((round(w*S),round(w*other.h/other.w*S)),Image.Resampling.LANCZOS)
        self.im.paste(image,(round(x*S),round(y*S)))
    def save(self,name):
        self.im.save(OUT/name)

def phone(title, nav=None):
    c=C(390,740)
    c.box(1,1,388,738,WHITE,INK,28,2)
    c.txt(23,15,'9:41',12,bold=True)
    for i in range(4): c.line([(294+i*4,24),(294+i*4,24-(i+1)*2)],INK,2)
    c.txt(315,16,'Wi-Fi',9)
    c.box(347,15,17,9,WHITE,INK,2,1)
    c.box(349,17,11,5,INK,None,0,0)
    c.line([(365,18),(365,21)],INK,1.5)
    if nav: c.txt(24,51,title,20,bold=True)
    else:
        c.line([(25,52),(18,60),(25,68)],INK,2)
        c.txt(43,51,title,20,bold=True)
    c.box(308,45,61,28,WHITE,INK,14,1)
    c.txt(321,53,'•••',12,bold=True)
    c.ellipse(350,53,12,12,WHITE,INK,1.5)
    c.line([(16,91),(374,91)],RULE,1)
    if nav:
        c.line([(1,682),(389,682)],INK,1.5)
        for i,t in enumerate(['闯关','复盘','我的']):
            x=65+i*130
            if t==nav: c.box(x-34,691,68,27,YELLOW,INK,8,1.5)
            c.txt(x,698,t,14,bold=t==nav,center=True)
    c.line([(150,728),(240,728)],INK,3)
    return c

def progress(c, n=2, xp=10):
    for i in range(5): c.box(24+i*70,110,60,8,YELLOW if i<n else '#EEEDEB',None,4,0)
    c.txt(24,137,f'第 {n} / 5 题',14,bold=True)
    c.pill(137,131,'单选',PALE_Y,52)
    c.txt(304,139,str(xp)+' XP',13,bold=True)

def home():
    c=phone('LevelUProject','闯关')
    c.box(24,111,342,105,PALE_Y,INK,15,2)
    c.txt(40,132,'今天想搞懂啥？',23,bold=True)
    c.txt(40,174,'把知识变成你的闯关。',13)
    c.mascot(267,119,.61)
    c.box(24,237,342,116,WHITE,INK,12,2)
    c.line([(39,251),(39,314)],'#E7AEA5',1)
    c.para(49,255,'我想搞懂 RAG，\n以及它和模型训练的区别',298,17)
    c.txt(40,328,'输入一句话，或粘贴一段学习材料',12,MUTED)
    c.txt(24,378,'也可以导入材料',14,bold=True)
    for i,t in enumerate(['文档','网页','视频']):
        c.box(24+i*119,405,104,47,WHITE,INK,10,2)
        c.txt(76+i*119,420,t,15,bold=True,center=True)
    c.txt(24,479,'联网补充 · 已开启',14)
    c.txt(280,479,'更多设置',13,MUTED)
    c.button(24,521,342,'开始生成关卡')
    c.txt(24,602,'试试：',13,MUTED)
    c.pill(76,593,'RAG 入门',PALE_B,93)
    c.pill(183,593,'理财基础',WHITE,93)
    return c

def sources():
    c=phone('确认学习材料')
    c.txt(24,115,'RAG 入门',25,bold=True)
    c.txt(24,153,'先确认资料，再开始闯关。',14,MUTED)
    for y,title,sub in [(197,'RAG 学习笔记.pdf','8 页 · 已解析'),(292,'网页资料 · 2 篇','已提取正文 · 可查看原文')]:
        c.box(24,y,342,78,WHITE,INK,12,2)
        c.box(40,y+19,34,40,PALE_B,INK,5,1.5)
        c.txt(86,y+18,title,17,bold=True)
        c.txt(86,y+49,sub,12,MUTED)
    c.txt(24,400,'这次会学到',19,bold=True)
    for i,t in enumerate(['检索与生成的基本流程','怎样将资料加入回答上下文','RAG 与模型训练的区别']):
        c.ellipse(25,440+i*35,7,7,YELLOW,INK,1)
        c.txt(43,435+i*35,t,15)
    c.line([(24,550),(366,550)],RULE,1)
    c.txt(24,570,'允许联网补充资料',15)
    c.pill(302,563,'开启',PALE_G,64)
    c.button(24,631,342,'确认材料，生成关卡')
    return c

def generating():
    c=phone('正在准备关卡')
    c.mascot(126,125,1.1,'thinking')
    c.txt(195,262,'知识正在变成关卡',24,bold=True,center=True)
    steps=[('材料准备完成','你的学习资料已保留',True),('联网获取并整理知识点','围绕主题补充必要信息',True),('生成题目与讲解','正在准备 5 道题目',False),('检查题目','完成后即可开始答题',None)]
    for i,(t,sub,done) in enumerate(steps):
        y=333+i*65
        if i<3: c.line([(42,y+20),(42,y+67)],RULE,2)
        c.ellipse(30,y,24,24,GREEN if done else YELLOW if done is False else WHITE,INK,2)
        if done: c.mark(36,y+7,11)
        elif done is False: c.txt(42,y+5,'…',12,bold=True,center=True)
        c.txt(76,y,t,17,bold=True)
        c.txt(76,y+29,sub,12,MUTED)
    c.button(24,631,342,'返回修改主题',secondary=True)
    return c

def quiz():
    c=phone('RAG 入门')
    progress(c)
    c.para(24,194,'RAG 在生成回答前，通常先做哪一步？',342,23,bold=True,leading=1.5)
    opts=['检索与问题相关的资料','重新训练整个大模型','删除历史知识','随机选择一段答案']
    for i,t in enumerate(opts):
        y=315+i*71
        c.box(24,y,342,55,PALE_B if i==0 else WHITE,BLUE if i==0 else INK,12,2.5 if i==0 else 2)
        c.txt(42,y+19,chr(65+i),17,bold=True)
        c.txt(77,y+19,t,16)
        if i==0: c.mark(333,y+19,13)
    c.txt(195,635,'选中后，立即查看答案和讲解',13,MUTED,center=True)
    return c

def feedback():
    c=phone('RAG 入门')
    progress(c)
    c.para(24,180,'RAG 在生成回答前，通常先做哪一步？',342,20,bold=True,leading=1.45)
    c.box(24,267,342,96,PALE_R,RED,12,2)
    c.mark(40,286,11,False)
    c.txt(60,285,'你的答案：B  重新训练整个模型',14)
    c.mark(40,324,11)
    c.txt(60,324,'正确答案：A  先检索相关资料',14,bold=True)
    c.box(24,386,254,37,PALE_Y,INK,10,2)
    c.txt(37,398,'这题拐了个弯，拆开看看。',14,bold=True)
    c.mascot(291,371,.5,'thinking')
    c.txt(24,452,'先查资料，再生成。',20,bold=True)
    c.para(24,491,'RAG 先检索相关资料，再把资料提供给模型生成回答。使用新资料，不等于重新训练整个模型。',342,16,leading=1.6)
    c.txt(24,588,'来源：学习笔记    查看原文 / 展开讲解',12,MUTED)
    c.button(24,631,342,'看懂了，下一题')
    return c

def report():
    c=phone('本轮复盘报告')
    c.box(24,113,342,65,PALE_Y,INK,12,2)
    c.txt(40,133,'这一关，拿下！',24,bold=True)
    c.mascot(288,113,.48)
    for x,v,l in [(80,'80%','正确率'),(195,'4 / 5','答对题数'),(310,'2:18','学习用时')]:
        c.txt(x,207,v,29,bold=True,center=True)
        c.txt(x,250,l,12,MUTED,center=True)
    c.line([(24,284),(366,284)],INK,1.5)
    c.box(24,305,342,40,PALE_G,None,8,0)
    c.txt(40,318,'本轮收获    +40 XP     +8 金币',15,bold=True)
    c.txt(24,374,'三句话，记住这一关',19,bold=True)
    summaries=['先检索资料，再结合资料生成回答。','检索结果会作为上下文提供给模型。','更新资料与重新训练模型是两件事。']
    y=414
    for i,t in enumerate(summaries):
        c.txt(26,y,str(i+1),15,bold=True)
        y=c.para(50,y,t,311,15,leading=1.55)+14
    c.box(24,552,342,56,PALE_R,RED,10,1.5)
    c.txt(38,564,'需要巩固',12,bold=True)
    c.txt(38,584,'RAG 与模型训练的区别',14)
    c.button(24,635,164,'去复习错题')
    c.button(203,635,163,'分享收获',secondary=True)
    return c

def review():
    c=phone('我的学习进展','复盘')
    c.txt(24,116,'本周搞懂了 7 个主题',23,bold=True)
    c.txt(24,155,'一点点积累，也会很有分量。',14,MUTED)
    for x,v,l in [(83,'18','累计通关'),(216,'82%','累计正确率'),(328,'6 天','学习天数')]:
        c.txt(x,207,v,28,bold=True,center=True);c.txt(x,247,l,12,MUTED,center=True)
    c.box(24,289,342,99,PALE_Y,INK,12,2)
    c.txt(40,309,'还有 3 道错题，等你拿下',18,bold=True)
    c.txt(40,348,'旧识重温，让知识记得更牢。',13)
    c.txt(320,349,'去复习',13,bold=True)
    c.txt(24,416,'近 7 天正确率',17,bold=True)
    for y,l in [(456,'100%'),(499,'80%'),(541,'60%')]:
        c.txt(24,y-5,l,10,MUTED);c.line([(64,y),(361,y)],RULE,1)
    pts=[(70,528),(114,509),(160,518),(205,486),(250,493),(298,473),(348,478)]
    c.line(pts,BLUE,3)
    for x,y in pts: c.ellipse(x-3,y-3,6,6,BLUE,None,0)
    c.txt(67,559,'10/05',10,MUTED);c.txt(318,559,'10/11',10,MUTED)
    c.button(24,606,342,'查看本周复盘报告',secondary=True)
    return c

def wrongs():
    c=phone('错题本')
    c.txt(24,115,'把不会，变成会。',24,bold=True)
    for x,t,w,fill in [(24,'待复习 3',100,YELLOW),(137,'全部',72,WHITE),(221,'已巩固',88,WHITE)]:c.pill(x,168,t,fill,w)
    rows=[('RAG 入门','检索与模型训练有什么区别？','昨天答错 · 今日待复习'),('RAG 入门','哪些资料可以作为回答上下文？','2 天前答错 · 今日待复习'),('学习方法','怎样安排一次有效的间隔复习？','3 天前答错 · 今日待复习')]
    for i,(topic,t,sub) in enumerate(rows):
        y=224+i*127
        c.box(24,y,342,108,WHITE,INK,12,2)
        c.pill(38,y+12,topic,PALE_B,85)
        c.txt(38,y+50,t,15,bold=True)
        c.txt(38,y+82,sub,12,MUTED)
    c.button(24,631,342,'开始旧识重温 · 3 题')
    return c

def library():
    c=phone('我的知识库')
    c.txt(24,116,'你的资料，也能闯关。',23,bold=True)
    c.box(24,164,342,43,WHITE,INK,10,1.5)
    c.txt(40,178,'搜索文件夹或材料',14,MUTED)
    folders=[('AI 入门笔记','6 份材料 · 3 套关卡',PALE_B),('产品设计阅读','4 份材料 · 最近学习过',PALE_Y),('面试准备','8 份材料 · 1 份解析中',PALE_G)]
    for i,(t,sub,col) in enumerate(folders):
        y=239+i*112
        c.poly([(28,y+12),(51,y+12),(59,y+22),(89,y+22),(89,y+77),(28,y+77)],col,INK,2)
        c.txt(107,y+26,t,18,bold=True)
        c.txt(107,y+58,sub,12,MUTED)
        c.line([(24,y+97),(366,y+97)],RULE,1)
    c.txt(24,601,'选择一个文件夹，即可用自己的材料出题。',13,MUTED)
    c.button(24,646,342,'新建知识库文件夹')
    return c

def pk():
    c=phone('好友挑战')
    c.pill(24,111,'扩展玩法',PALE_B,86)
    c.txt(24,157,'同一关，看看谁更懂！',23,bold=True)
    c.box(24,213,342,189,PALE_Y,INK,14,2)
    c.mascot(53,228,.7)
    c.ellipse(261,243,58,58,YELLOW,INK,2)
    c.txt(290,258,'林',25,bold=True,center=True)
    c.txt(195,276,'VS',25,bold=True,center=True)
    c.txt(92,339,'你',16,bold=True,center=True)
    c.txt(290,339,'好友小林',16,bold=True,center=True)
    c.txt(195,371,'双方使用同一套题目',12,MUTED,center=True)
    c.txt(24,436,'本轮挑战',18,bold=True)
    c.txt(24,478,'RAG 入门 · 5 题 · 单选 / 多选 / 判断',14)
    c.txt(24,518,'赛后一起看讲解，把知识带走。',14,MUTED)
    c.button(24,588,342,'邀请微信好友')
    c.txt(195,668,'查看领域排行榜',13,bold=True,center=True)
    return c

def membership():
    c=phone('会员与解析权益')
    c.pill(24,111,'扩展功能 · 演示权益',PALE_B,153)
    c.txt(24,157,'给学习，多一点工具。',23,bold=True)
    c.box(24,213,342,161,WHITE,INK,13,2)
    c.txt(40,233,'基础体验',20,bold=True)
    c.para(40,275,'主题和文本闯关\n答题讲解与本轮报告\n个人学习记录',300,15,leading=1.8)
    c.box(24,398,342,175,PALE_Y,INK,13,2)
    c.txt(40,418,'VIP 学习计划',20,bold=True)
    c.txt(40,457,'价格待定',24,bold=True)
    c.para(40,501,'更多解析额度、进阶学习权益。\n套餐和具体额度在此进行对比。',300,14,leading=1.7)
    c.txt(24,595,'高级解析包 / 超大文档按量 / 企业定制',12,MUTED)
    c.button(24,641,342,'查看套餐详情')
    return c

def poster():
    c=phone('分享这次学习收获')
    c.box(35,111,320,479,PALE_Y,INK,16,2)
    c.txt(55,133,'LevelUProject',18,bold=True)
    c.line([(55,168),(335,168)],INK,1.5)
    c.para(55,192,'今天，我把\nRAG 搞懂了一点！',280,27,bold=True,leading=1.5)
    c.mascot(132,286,1.0)
    c.para(55,414,'先找到相关资料，\n再让回答更有依据。',280,18,bold=True,leading=1.6)
    c.box(55,504,62,62,WHITE,INK,8,1.5)
    c.ellipse(69,518,34,34,WHITE,INK,1.5)
    c.txt(130,512,'扫码，闯过你的第一关',14,bold=True)
    c.txt(130,543,'小程序码占位 · 原型示例',11,MUTED)
    c.button(24,634,164,'保存海报')
    c.button(203,634,163,'分享给好友',secondary=True)
    return c

def sheet(name,title,subtitle,items):
    c=C(1440,1940,'#F2F5F9')
    c.txt(48,40,title,38,bold=True)
    c.txt(48,102,subtitle,18,MUTED)
    c.line([(48,145),(1392,145)],INK,2)
    for i,(label,caption,maker) in enumerate(items):
        x=48+(i%3)*456;y=178+(i//3)*844
        c.txt(x,y,label,22,bold=True)
        c.txt(x,y+37,caption,13,MUTED)
        c.paste(maker(),x,y+72,400)
    c.line([(48,1875),(1392,1875)],INK,1)
    c.txt(48,1898,'LevelUProject · 第二轮静态草图 · A 为候选示意 · 内容与数据均为演示',14,MUTED)
    c.txt(1263,1898,'2026-10-11',14,MUTED)
    c.save(name)

def styleboard():
    c=C(1440,990,'#F2F5F9')
    c.txt(48,39,'LevelUProject · 校园漫画，自有一套',38,bold=True)
    c.txt(48,103,'白纸阅读面、课本黄主行动、蓝色章节线；借鉴规范完整性，独立设计角色与版面。',18,MUTED)
    c.box(48,160,850,296,PALE_Y,INK,20,3)
    c.para(79,195,'今天卡住的知识，\n明天就是你的拿手题。',590,38,bold=True,leading=1.5)
    c.txt(79,378,'粗墨线 · 漫画分格 · 夸张表情 · 轻松反馈',19)
    c.asset('A-u-book-spirit.png',655,239,205,187)
    c.pencil_line(80,354,401)
    c.txt(946,179,'候选 A · U 形书灵',23,bold=True)
    c.asset('A-u-book-spirit.png',1073,221,177,137)
    c.para(946,378,'用名字中的 U，长成一个学习搭子。\n角色待确认，题干与正文保持清楚。',442,17,leading=1.7)
    colors=[('纸白',WHITE),('墨黑',INK),('课本黄',YELLOW),('圆珠笔蓝',BLUE),('过关绿',GREEN),('订正红',RED)]
    for i,(n,col) in enumerate(colors):
        x=48+i*228
        c.box(x,500,201,46,col,INK,8,1.5)
        c.txt(x,560,n,16,bold=True);c.txt(x+85,563,col,13,MUTED)
    specs=[(48,'主要操作'),(504,'选中与正确'),(960,'答错也能继续学')]
    for x,t in specs:
        c.txt(x,626,t,22,bold=True)
        c.line([(x,669),(x+408,669)],INK,1.5)
    c.button(48,700,408,'开始生成关卡')
    c.button(48,780,408,'查看学习报告',secondary=True)
    c.txt(48,860,'按下感与硬边阴影，只强调主要操作。',14,MUTED)
    c.box(504,700,408,55,PALE_B,BLUE,12,2.5)
    c.txt(524,719,'A   检索与问题相关的资料',18,bold=True)
    c.mark(876,720,15)
    c.box(504,780,408,55,PALE_G,GREEN,12,2)
    c.mark(524,799,15)
    c.txt(555,799,'答对了！经验值 +10',18,bold=True)
    c.txt(504,860,'对错同时用文字和图标标识。',14,MUTED)
    c.box(960,700,408,135,PALE_R,RED,12,2)
    c.txt(981,722,'这题拐了个弯，一起拆开看。',19,bold=True)
    c.para(981,765,'先显示正确答案与核心讲解，\n看懂后继续下一题。',360,16,leading=1.6)
    c.txt(960,860,'讲解有分寸，反馈有温度。',14,MUTED)
    c.line([(48,919),(1392,919)],INK,1)
    c.txt(48,943,'第二轮风格示意 · 角色与组件待审阅 · 正式 HTML 等待确认',14,MUTED)
    c.save('视觉风格板-v2.png')

def mascot_board():
    c=C(1440,1000,'#F2F5F9')
    c.txt(48,41,'LevelUProject · 学习搭子，重新出场',38,bold=True)
    c.txt(48,104,'三个原创候选；本轮 UI 草图暂用 A，最终形象由你确认。',18,MUTED)
    items=[('A · U 形书灵（推荐）','A-u-book-spirit.png','名字中的 U，变成一本活起来的书。','品牌联系最直接，适合欢迎与闯关反馈。',PALE_B),('B · 涂鸦铅笔同学','B-pencil-student.png','从随手记下的问题，开始一次学习。','校园意味更强，动作与装扮便于扩展。',PALE_Y),('C · 纸团探险家','C-paper-explorer.png','把一次次尝试，变成下一步的灵感。','更有故事感，适合挑战、复习与成就。',PALE_G)]
    for i,(title,img,line1,line2,bg) in enumerate(items):
        x=48+i*456
        c.box(x+4,176,400,708,INK,INK,16,0)
        c.box(x,172,400,708,WHITE,INK,16,2)
        c.box(x+18,194,364,54,bg,None,10,0)
        c.txt(x+35,211,title,23,bold=True)
        c.asset(img,x+33,276,334,380)
        c.pencil_line(x+28,699,340)
        c.para(x+28,731,line1,343,18,bold=True,leading=1.6)
        c.para(x+28,792,line2,343,15,fill=MUTED,leading=1.6)
    c.txt(48,934,'角色候选阶段 · 图片均保留透明背景 · 表情与装扮在选定角色后再统一扩展',14,MUTED)
    c.save('吉祥物候选-v2.png')

def launch():
    c=phone('LevelUProject')
    c.txt(195,135,'LevelUProject',29,bold=True,center=True)
    c.pencil_line(95,179,200)
    c.txt(195,205,'把想学的，变成一关。',22,bold=True,center=True)
    c.asset('A-u-book-spirit.png',93,260,204,208)
    c.txt(195,505,'一个主题 / 一份文档 / 一段链接',14,MUTED,center=True)
    c.button(24,554,342,'微信登录并开始')
    c.button(24,624,342,'先体验一关',secondary=True,h=44)
    c.txt(195,696,'登录即同意用户协议与隐私政策',11,MUTED,center=True)
    return c

def combo():
    c=phone('RAG 入门')
    progress(c,3,30)
    c.txt(24,185,'先检索，再结合资料生成回答。',19,bold=True)
    c.box(24,252,342,287,PALE_Y,INK,16,2.5)
    c.pill(45,272,'连击记录',WHITE,88)
    c.txt(195,320,'连续答对 3 题',27,bold=True,center=True)
    c.asset('A-u-book-spirit.png',137,371,116,121)
    c.txt(195,513,'状态越来越稳了，继续！',15,bold=True,center=True)
    c.txt(195,585,'本轮共 5 题，每一题都有知识讲解。',13,MUTED,center=True)
    c.button(24,631,342,'继续闯关')
    return c

def friends():
    c=phone('好友')
    c.txt(24,117,'一起闯关的人',25,bold=True)
    c.txt(24,159,'从一个共同话题，开始一场知识对局。',14,MUTED)
    for i,(n,letter,topic,fill) in enumerate([('小林','林','RAG 入门',PALE_B),('阿周','周','学习方法',PALE_G),('夏夏','夏','计算机网络',PALE_Y)]):
        y=221+i*117
        c.ellipse(24,y+5,51,51,fill,INK,2)
        c.txt(49,y+20,letter,21,bold=True,center=True)
        c.txt(92,y+5,n,19,bold=True)
        c.txt(92,y+40,'最近学习：'+topic,12,MUTED)
        c.box(282,y+8,84,38,YELLOW,INK,10,1.5)
        c.txt(324,y+21,'发起 PK',13,bold=True,center=True)
        c.line([(24,y+87),(366,y+87)],RULE,1)
    c.button(24,631,342,'邀请微信好友')
    return c

def invitation():
    c=phone('邀请朋友一起学习')
    c.box(24,112,342,107,PALE_Y,INK,12,2)
    c.txt(40,134,'一起学，才有话聊。',22,bold=True)
    c.txt(40,178,'邀请朋友，完成他们的第一关。',13)
    c.txt(97,257,'3 位',29,bold=True,center=True)
    c.txt(97,300,'好友已加入',12,MUTED,center=True)
    c.txt(285,257,'2 位',29,bold=True,center=True)
    c.txt(285,300,'完成第一关',12,MUTED,center=True)
    c.line([(24,337),(366,337)],INK,1.5)
    c.txt(24,366,'邀请进度',18,bold=True)
    for i,(n,t,fill) in enumerate([('小林','已完成第一关',PALE_G),('阿周','已完成第一关',PALE_G),('夏夏','已加入，待首次闯关',PALE_Y)]):
        y=414+i*50
        c.txt(24,y,n,16,bold=True)
        c.pill(183,y-5,t,fill,183)
    c.txt(24,588,'一起点亮“学习搭子”邀请成就。',14,MUTED)
    c.button(24,631,342,'生成邀请卡，分享给好友')
    return c

def shop():
    c=phone('学习搭子装扮')
    c.txt(24,117,'让小U，有点你的样子。',23,bold=True)
    c.txt(24,158,'金币余额 80 · 通过学习积累',13,MUTED)
    c.box(24,195,342,188,PALE_B,INK,12,2)
    c.asset('A-u-book-spirit.png',128,208,134,126)
    c.txt(195,353,'经典书灵 · 已拥有',14,bold=True,center=True)
    for i,(t,price) in enumerate([('小书签',20),('笔记贴',40),('探险包',60)]):
        x=24+i*119
        c.box(x,411,104,144,WHITE,INK,10,1.5)
        if i==0:c.poly([(x+39,431),(x+66,431),(x+66,476),(x+53,465),(x+39,476)],YELLOW,INK,2)
        elif i==1:
            c.box(x+30,434,45,39,PALE_B,INK,4,1.5)
            c.line([(x+38,448),(x+67,448)],BLUE,2)
            c.line([(x+38,458),(x+61,458)],BLUE,2)
        else:
            c.box(x+32,435,43,43,YELLOW,INK,8,2)
            c.box(x+42,425,23,16,None,INK,5,2)
        c.txt(x+52,495,t,15,bold=True,center=True)
        c.txt(x+52,529,str(price)+' 金币',12,MUTED,center=True)
    c.txt(24,591,'装扮让学习更有趣，不影响答题成绩。',13,MUTED)
    c.button(24,631,342,'选择装扮，查看兑换详情')
    return c

def achievements():
    c=phone('学习成就')
    c.txt(24,117,'每次搞懂，都算数。',24,bold=True)
    c.txt(24,158,'已解锁 3 / 9 · 下一枚，认真复习',14,MUTED)
    names=['第一关','知识收集','认真订正','复习三次','持续学习','主题探索','知识分享','好友挑战','累计十关']
    for i,t in enumerate(names):
        x=24+(i%3)*119;y=221+(i//3)*119; unlocked=i<3
        c.box(x,y,104,100,[PALE_B,PALE_Y,PALE_G][i] if unlocked else WHITE,INK if unlocked else RULE,10,1.5)
        c.poly([(x+36,y+44),(x+32,y+71),(x+52,y+63),(x+72,y+71),(x+68,y+44)],YELLOW if unlocked else '#EEEDEB',INK if unlocked else RULE,1.5)
        c.ellipse(x+31,y+13,42,42,WHITE,INK if unlocked else RULE,1.5)
        if unlocked:c.mark(x+43,y+26,17)
        else:c.txt(x+52,y+25,str(i+1),16,fill=MUTED,center=True)
        c.txt(x+52,y+79,t,13,bold=unlocked,center=True)
    c.box(24,598,342,81,PALE_Y,INK,12,2)
    c.txt(40,614,'下一枚：复习三次',16,bold=True)
    c.txt(40,650,'已完成 2 次，再重温一轮就点亮。',13)
    return c

styleboard()
mascot_board()
sheet('草图-01-核心学习-v2.png','LevelUProject · 从一个问题，到一次搞懂','第二轮六个代表屏；完整范围见设计提案的 69 项页面与状态清单。',[
    ('L01 · 首页输入','一个输入框，多种材料入口',home),
    ('L06 · 来源确认','确认材料、范围和联网补充',sources),
    ('L07 · AI 生成','显示真实步骤语义，允许返回',generating),
    ('L09 · 闯关答题','一题一屏，单选即时反馈',quiz),
    ('L13 · 订正与讲解','答错也给正确答案与解释',feedback),
    ('L17 · 本轮复盘','总结、薄弱点与下一步行动',report),
])
sheet('草图-02-复盘与扩展-v2.png','LevelUProject · 让知识留下来','个人学习中心属于核心；知识库、社交挑战与会员属于扩展，分享属于核心。',[
    ('R01 · 学习概览','累计学习、待复习与趋势',review),
    ('R08 · 错题本','按主题重温，形成复习闭环',wrongs),
    ('K01 · 私有知识库','从自己的资料中生成关卡',library),
    ('S02 · 好友挑战','同题挑战，赛后统一复盘',pk),
    ('A04 · 会员与解析权益','套餐与额度清楚展示，价格待定',membership),
    ('L18 · 分享海报','展示知识收获，预留小程序码',poster),
])
sheet('草图-03-补充页面-v2.png','LevelUProject · 补齐每一种学习时刻','对照参考补充的六个代表屏；数值均为演示，角色使用候选 A，商业规则待确认。',[
    ('L19 · 启动与首次进入','品牌、游客体验与主动登录',launch),
    ('L21 · 连击反馈','记录连续答对，不中断知识讲解',combo),
    ('S07 · 好友列表','从好友发起一次共同主题挑战',friends),
    ('S08 · 邀请有礼','关注邀请后的首次学习进度',invitation),
    ('A10 · 金币装扮商店','装扮兑换，价格均为演示数值',shop),
    ('A11 · 成就徽章墙','已获得、即将获得与未获得',achievements),
])
print('Created 5 second-round review images with 18 representative screens. No HTML prototype was created.')
