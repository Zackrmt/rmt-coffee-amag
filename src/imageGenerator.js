/**
 * imageGenerator.js
 * Created by: Zackrmt
 * Created at: 2025-06-04 13:31:10 UTC
 */

const { createCanvas, loadImage, registerFont } = require('canvas');

class ImageGenerator {
    constructor() {
        this.aspectRatio = 4/5; // Instagram vertical size
        this.width = 1080;      // Standard Instagram width
        this.height = this.width * (1/this.aspectRatio); // 1350px
        
        // Register custom fonts if needed
        // registerFont('path/to/font.ttf', { family: 'CustomFont' });
    }

    async generateDesign1(data) {
        const canvas = createCanvas(this.width, this.height);
        const ctx = canvas.getContext('2d');

        // Modern split layout
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, this.width, this.height);

        // MTLE 2025 Header
        ctx.font = 'bold 72px Arial';
        ctx.fillStyle = '#1E1E1E';
        ctx.textAlign = 'center';
        ctx.fillText('MTLE 2025', this.width/2, 100);

        // Split layout
        const leftWidth = this.width * 0.4;
        
        // Left side icons
        ctx.font = '64px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('📚', leftWidth/2, 300);
        
        // Right side content
        ctx.font = 'bold 48px Arial';
        ctx.textAlign = 'left';
        ctx.fillText('Study Statistics', leftWidth + 50, 250);

        // Study times
        this.drawProgressBar(ctx, leftWidth + 50, 350, data.goalTime, data.actualTime, '⏰');
        this.drawProgressBar(ctx, leftWidth + 50, 500, data.breakTime, data.totalTime, '☕');

        // Subject
        ctx.font = '36px Arial';
        ctx.fillText(`Subject: ${data.subject}`, leftWidth + 50, 650);

        // Motivational message
        ctx.font = 'bold 42px Arial';
        ctx.fillText('Keep it up! 🌟', leftWidth + 50, 750);

        return canvas.toBuffer('image/png');
    }

    async generateDesign2(data) {
        const canvas = createCanvas(this.width, this.height);
        const ctx = canvas.getContext('2d');

        // Dual circle design
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, this.width, this.height);

        // MTLE 2025 Header
        ctx.font = 'bold 72px Arial';
        ctx.fillStyle = '#1E1E1E';
        ctx.textAlign = 'center';
        ctx.fillText('MTLE 2025', this.width/2, 100);

        // Draw study circle
        this.drawProgressCircle(ctx, this.width * 0.3, 300, 100, data.actualTime/data.goalTime);
        
        // Draw break circle
        this.drawProgressCircle(ctx, this.width * 0.7, 300, 100, data.breakTime/data.totalTime);

        // Session details
        ctx.font = 'bold 48px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('Session Details', this.width/2, 600);

        // Stats
        this.drawStats(ctx, data, 700);

        return canvas.toBuffer('image/png');
    }

    async generateDesign3(data) {
        const canvas = createCanvas(this.width, this.height);
        const ctx = canvas.getContext('2d');

        // Modern dashboard
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, this.width, this.height);

        // MTLE 2025 Header
        ctx.font = 'bold 72px Arial';
        ctx.fillStyle = '#1E1E1E';
        ctx.textAlign = 'center';
        ctx.fillText('MTLE 2025', this.width/2, 100);

        // Large central circle
        this.drawProgressCircle(ctx, this.width/2, 350, 150, data.actualTime/data.goalTime);

        // Stats dashboard
        ctx.font = 'bold 36px Arial';
        ctx.textAlign = 'left';
        ctx.fillText(`📚 Subject: ${data.subject}`, 100, 600);
        ctx.fillText(`🎯 Goal: ${this.formatTime(data.goalTime)}`, 100, 650);
        ctx.fillText(`⏰ Actual: ${this.formatTime(data.actualTime)}`, 100, 700);
        ctx.fillText(`☕ Breaks: ${this.formatTime(data.breakTime)}`, 100, 750);

        // Progress bar
        this.drawProgressBar(ctx, 100, 800, data.goalTime, data.actualTime);

        return canvas.toBuffer('image/png');
    }

    drawProgressCircle(ctx, x, y, radius, progress) {
        // Background circle
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = '#F0F0F0';
        ctx.fill();

        // Progress arc
        ctx.beginPath();
        ctx.arc(x, y, radius, -Math.PI/2, (-Math.PI/2) + (Math.PI * 2 * progress));
        ctx.fillStyle = '#4CAF50';
        ctx.fill();

        // Center circle
        ctx.beginPath();
        ctx.arc(x, y, radius * 0.8, 0, Math.PI * 2);
        ctx.fillStyle = '#FFFFFF';
        ctx.fill();

        // Progress text
        ctx.font = 'bold 36px Arial';
        ctx.fillStyle = '#1E1E1E';
        ctx.textAlign = 'center';
        ctx.fillText(`${Math.round(progress * 100)}%`, x, y);
    }

    drawProgressBar(ctx, x, y, goal, actual, icon = '') {
        const width = 400;
        const height = 30;
        const progress = Math.min(actual/goal, 1);

        // Background
        ctx.fillStyle = '#F0F0F0';
        ctx.fillRect(x, y, width, height);

        // Progress
        ctx.fillStyle = '#4CAF50';
        ctx.fillRect(x, y, width * progress, height);

        // Text
        ctx.font = '24px Arial';
        ctx.fillStyle = '#1E1E1E';
        ctx.textAlign = 'left';
        ctx.fillText(`${icon} ${this.formatTime(actual)} / ${this.formatTime(goal)}`, x, y - 10);
    }

    drawStats(ctx, data, y) {
        ctx.font = '36px Arial';
        ctx.textAlign = 'left';
        const x = 100;

        ctx.fillText(`📚 Goal: ${this.formatTime(data.goalTime)}`, x, y);
        ctx.fillText(`⏱️ Actual: ${this.formatTime(data.actualTime)}`, x, y + 50);
        ctx.fillText(`☕ Breaks: ${this.formatTime(data.breakTime)}`, x, y + 100);
    }

    formatTime(minutes) {
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        return `${hours}:${mins.toString().padStart(2, '0')}`;
    }
}

module.exports = new ImageGenerator();
