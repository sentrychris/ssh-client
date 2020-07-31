const path = require('path');
const MiniCssExtractPlugin = require("mini-css-extract-plugin");

module.exports = {
    mode: 'development',
    devtool: 'inline-source-map',
    entry: [
        './static/js/index.js',
        './static/styles/app.scss'
    ],
    output: {
        path: path.resolve(__dirname, 'static'),
        filename: 'js/main.min.js',
    },
    plugins: [
        new MiniCssExtractPlugin({
            filename: "styles/[name].min.css",
            chunkFilename: "styles/[id].min.css"
        })
    ],
    module: {
        rules: [
            {
                test: /\.s?css$/,
                use: [
                    MiniCssExtractPlugin.loader,
                    "css-loader",
                    "sass-loader"
                ]
            },
            {
                test: /\.js$/,
                exclude: /node_modules/,
                use: []
            },
        ],
    }
};