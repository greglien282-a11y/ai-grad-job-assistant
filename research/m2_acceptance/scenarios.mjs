// Public fictional materials only. No real identity, job ad or resume is collected.
const school = '教育经历\n合成大学 · 计算机本科课程 · 应届生。\n\n'
export const visionJD = '公开合成：视觉算法实习生\n必备：Python基础。\n加分：图像处理课程记录。\n待核实：是否要求部署经历。'
export const scenarios = [
 { id:'S01', name:'几乎没有项目的本科生', format:'paste', raw:school+'技能\n我正在学习Python，暂无项目或实习经历。', jd:visionJD, notes:['仅教育自述与学习背景，不应生成项目或量化结果。'] },
 { id:'S02', name:'只有课程作业', format:'txt', raw:school+'项目经历\n我编写了Python课程作业中的图像读取脚本。\n\n技能\n我阅读了测试课程笔记。', jd:visionJD, notes:['课程材料不得自动变成生产项目。'] },
 { id:'S03', name:'实验室研究但没有实习', format:'md', raw:school+'项目经历\n我整理了公开图像数据集的标注样例。\n\n我在合成实验室阅读论文，没有正式实习。', jd:visionJD, notes:['研究活动与正式实习独立表达。'] },
 { id:'S04', name:'团队项目但个人职责有限', format:'txt', raw:school+'项目经历\n团队完成了模型训练，我只整理公开样例。\n\n技能\nPython课程基础。', jd:visionJD, notes:['团队来源保留为背景，不能去掉“只”。'] },
 { id:'S05', name:'Python基础但未部署', format:'md', raw:school+'技能\nPython课程基础。\n\n项目经历\n我没有部署服务，计划学习OpenCV。', jd:visionJD, notes:['部署缺口由用户自评；没有记录不等于系统证明不会。'] },
 { id:'S06', name:'输入含明显夸大但未经证实', format:'paste', raw:school+'项目经历\n我独立部署了商业系统，准确率提升99%。\n\n技能\nPython基础。', jd:visionJD, notes:['故意提供未经支持的夸大原文。系统不新增它，但现有本地自述合同不会证明或识别其真实性；不据此声称已防夸大。'], exaggeration:true },
 { id:'S07', name:'中文双栏PDF', format:'pdf', raw:school+'项目经历\n我编写了Python图像读取脚本。\n\n团队负责演示，我只整理记录。\n\n技能\nPython课程基础。', jd:visionJD, notes:['检查列顺序、标题和限定语，坐标不是文本引用。'] },
 { id:'S08', name:'含表格DOCX', format:'docx', raw:school+'项目经历\n我编写了Python课程脚本。\n\n技能\nPython课程基础。\n\n团队负责演示，我没有参与部署。', jd:visionJD, notes:['表格摊平必须显式核对，不保证视觉结构。'] },
 { id:'S09', name:'一份材料投视觉与后端', format:'md', raw:school+'项目经历\n我编写了Python图像读取脚本。\n\n技能\nPython与测试课程基础。', jd:visionJD, twoRoles:true, notes:['独立选择、版式、编辑和复习；原文只导入一次。'] },
 { id:'S10', name:'JD条件冲突与含糊要求', format:'txt', raw:school+'项目经历\n我编写了Python课程脚本。', jd:'公开合成：实习岗位\n必须掌握Python。\n不要求Python经验。\n加分：测试课程。\n待核实：所谓能独当一面是什么意思。', conflict:true, notes:['冲突条件保持待核实，不强制归为必备。'] },
 { id:'S11', name:'Unicode与跨段引用', format:'md', raw:'教育经历\r\n合成大学本科课程。\r\n\r\n项目经历\r\n👩‍💻 é 我编写了Python脚本。\r\n\r\n技能\r\nPython课程基础。', crossQuote:true, jd:visionJD, notes:['ZWJ、组合字符、CRLF及跨段区间以code points核对。'] },
 { id:'S12', name:'重复原句与本地拒绝', format:'txt', raw:school+'项目经历\n我编写了Python脚本。\n\n我编写了Python脚本。', rejectDuplicate:true, jd:visionJD, notes:['精确拒绝后重复原句不能复活；不证明R03语义变体已解决。'] },
]
