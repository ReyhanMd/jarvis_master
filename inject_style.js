l// JavaScript to change paragraph color to blue text with red background
(function() {
    // Try multiple selectors to find the element
    const selectors = [
        'p[data-cursor-element-id="cursor-el-117"]',
        'p:contains("We\'re excited to release")',
        'main article p:first-of-type'
    ];
    
    let element = null;
    for (const selector of selectors) {
        if (selector.includes('contains')) {
            // For text-based search
            const paragraphs = document.querySelectorAll('p');
            for (const p of paragraphs) {
                if (p.textContent.includes("We're excited to release")) {
                    element = p;
                    break;
                }
            }
        } else {
            element = document.querySelector(selector);
        }
        if (element) break;
    }
    
    if (element) {
        element.style.color = 'blue';
        element.style.backgroundColor = 'red';
        console.log('Style applied successfully!', element);
    } else {
        console.log('Element not found. Trying all paragraphs...');
        const allParagraphs = document.querySelectorAll('main article p');
        if (allParagraphs.length > 0) {
            allParagraphs[0].style.color = 'blue';
            allParagraphs[0].style.backgroundColor = 'red';
            console.log('Applied to first paragraph in article');
        }
    }
})();









